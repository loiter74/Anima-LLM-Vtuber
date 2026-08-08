from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tooling.execution_feedback import (
    ExecutionPlanManifest,
    FailureLedger,
    FailureRecord,
    FeedbackStatus,
    IterationPlanStore,
    PlanAggregateStatus,
    PlanRecoveryManager,
    PlanStepCheckpoint,
    PlanStepSpec,
    aggregate_plan_status,
    fingerprint_failure,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _plan() -> ExecutionPlanManifest:
    return ExecutionPlanManifest(
        run_id="run-1",
        input_fingerprint="a" * 64,
        steps=(
            PlanStepSpec(id="prepare", action_kind="test"),
            PlanStepSpec(
                id="execute",
                action_kind="test",
                depends_on=("prepare",),
            ),
            PlanStepSpec(
                id="verify",
                action_kind="test",
                depends_on=("execute",),
            ),
            PlanStepSpec(id="independent", action_kind="test"),
        ),
    )


def _checkpoint(step_id: str, fingerprint: str) -> PlanStepCheckpoint:
    return PlanStepCheckpoint(
        run_id="run-1",
        step_id=step_id,
        status=FeedbackStatus.PASSED,
        reuse_fingerprint=fingerprint,
        evidence_refs=(f"evidence:{step_id}",),
        result_reference=f"result:{step_id}",
        committed_at=NOW,
    )


def _failure_record(
    fingerprint: str,
    *,
    run_id: str,
    occurrence: int,
) -> FailureRecord:
    return FailureRecord(
        fingerprint=fingerprint,
        run_id=run_id,
        step_id="execute",
        step_kind="docker-build",
        error_code="build-timeout",
        failure_layer="environment",
        occurred_at=NOW + timedelta(seconds=occurrence),
        evidence_refs=(f"evidence:failure:{occurrence}",),
        location="runtime_lifecycle:build",
    )


def test_changed_step_invalidates_only_itself_and_transitive_downstream(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    manager = PlanRecoveryManager(store)
    plan = _plan()
    expected = {
        "prepare": "1" * 64,
        "execute": "2" * 64,
        "verify": "3" * 64,
        "independent": "4" * 64,
    }
    for step_id, fingerprint in expected.items():
        manager.record(_checkpoint(step_id, fingerprint))
    changed = dict(expected)
    changed["execute"] = "9" * 64

    recovery = manager.recover(
        plan,
        expected_fingerprints=changed,
        evidence_exists=lambda _reference: True,
    )

    assert recovery.reusable_steps == ("prepare", "independent")
    assert recovery.invalidated_steps == {
        "execute": "reuse fingerprint changed",
        "verify": "dependency execute is invalid",
    }


def test_missing_evidence_invalidates_checkpoint_and_downstream(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    manager = PlanRecoveryManager(store)
    plan = _plan()
    expected = {
        "prepare": "1" * 64,
        "execute": "2" * 64,
        "verify": "3" * 64,
        "independent": "4" * 64,
    }
    for step_id, fingerprint in expected.items():
        manager.record(_checkpoint(step_id, fingerprint))

    recovery = manager.recover(
        plan,
        expected_fingerprints=expected,
        evidence_exists=lambda reference: reference != "evidence:execute",
    )

    assert recovery.reusable_steps == ("prepare", "independent")
    assert recovery.invalidated_steps["execute"] == "checkpoint evidence is missing"
    assert recovery.invalidated_steps["verify"] == "dependency execute is invalid"


def test_nonterminal_required_step_cannot_aggregate_as_success() -> None:
    plan = _plan()

    in_progress = aggregate_plan_status(
        plan,
        {
            "prepare": FeedbackStatus.PASSED,
            "execute": FeedbackStatus.IN_PROGRESS,
            "verify": FeedbackStatus.BLOCKED,
            "independent": FeedbackStatus.PASSED,
        },
    )
    complete = aggregate_plan_status(
        plan,
        {step.id: FeedbackStatus.PASSED for step in plan.steps},
    )

    assert in_progress.status is PlanAggregateStatus.IN_PROGRESS
    assert in_progress.nonpassing_required_steps == ("execute", "verify")
    assert complete.status is PlanAggregateStatus.PASSED


def test_failure_fingerprint_ignores_run_and_time_but_changes_with_root_inputs() -> None:
    first = fingerprint_failure(
        step_kind="docker-build",
        error_code="BUILD_TIMEOUT",
        failure_layer="environment",
        input_fingerprint="a" * 64,
        environment_fingerprint="b" * 64,
    )
    same = fingerprint_failure(
        step_kind="docker-build",
        error_code="build_timeout",
        failure_layer="environment",
        input_fingerprint="a" * 64,
        environment_fingerprint="b" * 64,
    )
    different_environment = fingerprint_failure(
        step_kind="docker-build",
        error_code="build_timeout",
        failure_layer="environment",
        input_fingerprint="a" * 64,
        environment_fingerprint="c" * 64,
    )

    assert first == same
    assert first != different_environment


def test_plan_allows_only_two_automatic_retries_for_same_failure(tmp_path) -> None:
    ledger = FailureLedger(IterationPlanStore(tmp_path))
    fingerprint = fingerprint_failure(
        step_kind="docker-build",
        error_code="build_timeout",
        failure_layer="environment",
        input_fingerprint="a" * 64,
        environment_fingerprint="b" * 64,
    )

    ledger.record(_failure_record(fingerprint, run_id="run-a", occurrence=1))
    assert ledger.authorize(fingerprint, run_id="run-a").allowed is True
    ledger.record(_failure_record(fingerprint, run_id="run-a", occurrence=2))
    assert ledger.authorize(fingerprint, run_id="run-a").allowed is True
    ledger.record(_failure_record(fingerprint, run_id="run-a", occurrence=3))

    refused = ledger.authorize(fingerprint, run_id="run-a")
    assert refused.allowed is False
    assert refused.reason == "automatic retry limit reached for this plan"


def test_fifth_failure_opens_circuit_and_sixth_is_refused_with_reflection(tmp_path) -> None:
    ledger = FailureLedger(IterationPlanStore(tmp_path))
    fingerprint = fingerprint_failure(
        step_kind="docker-build",
        error_code="build_timeout",
        failure_layer="environment",
        input_fingerprint="a" * 64,
        environment_fingerprint="b" * 64,
    )

    state = None
    for occurrence in range(1, 6):
        state = ledger.record(
            _failure_record(
                fingerprint,
                run_id=f"run-{occurrence}",
                occurrence=occurrence,
            )
        )

    assert state is not None
    assert state.circuit_open is True
    assert state.reflection is not None
    assert state.reflection.occurrence_count == 5
    assert state.reflection.evidence_refs == tuple(
        f"evidence:failure:{occurrence}" for occurrence in range(1, 6)
    )
    refused = ledger.authorize(fingerprint, run_id="run-6")
    assert refused.allowed is False
    assert refused.reflection == state.reflection


def test_audited_reset_supersedes_old_circuit_and_allows_new_fingerprint(tmp_path) -> None:
    ledger = FailureLedger(IterationPlanStore(tmp_path))
    old_fingerprint = "a" * 64
    new_fingerprint = "b" * 64
    for occurrence in range(1, 6):
        ledger.record(
            _failure_record(
                old_fingerprint,
                run_id=f"run-{occurrence}",
                occurrence=occurrence,
            )
        )

    reset = ledger.reset(
        old_fingerprint,
        new_fingerprint=new_fingerprint,
        reason="Docker environment fingerprint changed",
        reset_at=NOW + timedelta(minutes=1),
    )

    assert reset.superseded_by == new_fingerprint
    assert reset.reset_reason == "Docker environment fingerprint changed"
    assert ledger.authorize(new_fingerprint, run_id="run-new").allowed is True
