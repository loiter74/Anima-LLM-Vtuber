from __future__ import annotations

import pytest

from animetta.tools.minecraft.showcase.promotion import (
    AcceptanceLedger,
    AcceptanceLedgerStore,
    ArchitectureAudit,
    FailureCoverage,
    PromotionIdentity,
    RealAttempt,
)


def _identity(**updates: object) -> PromotionIdentity:
    payload: dict[str, object] = {
        "code_commit": "0123456789abcdef0123456789abcdef01234567",
        "code_tree_hash": "a" * 64,
        "runtime_identity": "voyager-runtime@sha256:runtime-a",
        "minecraft_version": "1.21",
        "scenario_hash": "b" * 64,
        "model_identity": "deepseek-chat@configured",
        "schema_hashes": {"stage_io_v2": "c" * 64, "gamebot_v2": "d" * 64},
    }
    payload.update(updates)
    return PromotionIdentity.model_validate(payload)


def _pass_through(ledger: AcceptanceLedger, last_gate: int) -> AcceptanceLedger:
    for ordinal in range(last_gate + 1):
        ledger = ledger.record_gate(
            gate=f"R{ordinal}",  # type: ignore[arg-type]
            status="passed",
            attempt_id=f"gate-r{ordinal}-001",
            started_at_ms=ordinal * 10,
            finished_at_ms=ordinal * 10 + 1,
            evidence_refs=(f"artifact:r{ordinal}",),
        )
    return ledger


def test_lower_layer_identity_changes_invalidate_only_affected_higher_gates() -> None:
    ledger = _pass_through(AcceptanceLedger(identity=_identity()), 6)

    runtime_changed = ledger.rebind_identity(
        _identity(runtime_identity="voyager-runtime@sha256:runtime-b")
    )
    model_changed = ledger.rebind_identity(_identity(model_identity="deepseek-chat@configured-v2"))

    assert runtime_changed.highest_current_passed_gate == "R4"
    assert runtime_changed.can_promote("R5") is True
    assert model_changed.highest_current_passed_gate == "R5"
    assert model_changed.can_promote("R6") is True


def test_failed_lower_gate_prevents_higher_promotion() -> None:
    ledger = _pass_through(AcceptanceLedger(identity=_identity()), 3)
    ledger = ledger.record_gate(
        gate="R4",
        status="failed",
        attempt_id="gate-r4-001",
        started_at_ms=100,
        finished_at_ms=110,
        evidence_refs=("replay:final20",),
        failure_code="OUTCOME_ERASED",
    )

    assert ledger.can_promote("R5") is False
    with pytest.raises(ValueError, match="PRIOR_GATE_NOT_PROMOTED"):
        ledger.record_gate(
            gate="R5",
            status="passed",
            attempt_id="gate-r5-001",
            started_at_ms=120,
            finished_at_ms=130,
            evidence_refs=("artifact:r5",),
        )


def test_second_same_stage_failure_blocks_r8_until_r4_and_r7_coverage_exist() -> None:
    ledger = AcceptanceLedger(identity=_identity())
    for ordinal in range(2):
        ledger = ledger.record_real_attempt(
            RealAttempt(
                attempt_id=f"real-combat-{ordinal + 1}",
                run_id=f"run-{ordinal + 1}",
                stage_id="combat",
                outcome="failed",
                failure_code="ENTITY_NOT_DEFEATED",
                failure_layer="verification",
                occurred_at_ms=100 + ordinal,
            )
        )

    assert ledger.failure_budget.r7_allowed is True
    assert ledger.failure_budget.r8_allowed is False
    assert ledger.failure_budget.required_actions == (
        "combat:ADD_MINIMAL_R7_REPRODUCTION_AND_R4_REPLAY",
    )

    covered = ledger.add_failure_coverage(
        FailureCoverage(
            stage_id="combat",
            deterministic_r4_ref="replay:combat-final21",
            minimal_r7_ref="micro-scene:combat",
            recorded_at_ms=200,
        )
    )

    assert covered.failure_budget.r8_allowed is True


def test_fifth_real_failure_requires_overall_architecture_audit() -> None:
    ledger = AcceptanceLedger(identity=_identity())
    for ordinal in range(5):
        ledger = ledger.record_real_attempt(
            RealAttempt(
                attempt_id=f"real-{ordinal + 1}",
                run_id=f"run-{ordinal + 1}",
                stage_id=f"stage-{ordinal + 1}",
                outcome="failed",
                failure_code="REAL_GATE_FAILED",
                failure_layer="execution",
                occurred_at_ms=100 + ordinal,
            )
        )

    assert ledger.failure_budget.total_failures == 5
    assert ledger.failure_budget.r7_allowed is False
    assert ledger.failure_budget.r8_allowed is False
    assert ledger.failure_budget.required_actions == ("PERFORM_OVERALL_ARCHITECTURE_AUDIT",)

    audited = ledger.record_architecture_audit(
        ArchitectureAudit(
            overall_failure_cause="Action settlement and scenario assumptions were coupled.",
            contributing_causes=("Unstable observations were treated as failed actions.",),
            systemic_changes=("Separate outcome, reconciliation, and verification state.",),
            evidence_refs=("replay:final20", "replay:final21"),
            recorded_at_ms=300,
        )
    )

    assert audited.failure_budget.r7_allowed is True


def test_acceptance_ledger_is_durable_and_rejects_hidden_duplicate_attempts(tmp_path) -> None:
    ledger = AcceptanceLedger(identity=_identity()).record_real_attempt(
        RealAttempt(
            attempt_id="real-001",
            run_id="run-001",
            stage_id="combat",
            outcome="failed",
            failure_code="ENTITY_NOT_DEFEATED",
            failure_layer="verification",
            occurred_at_ms=100,
        )
    )
    store = AcceptanceLedgerStore(tmp_path / "acceptance-ledger.json")
    store.save(ledger)

    restored = store.load()

    assert restored == ledger
    with pytest.raises(ValueError, match="DUPLICATE_REAL_ATTEMPT"):
        restored.record_real_attempt(ledger.real_attempts[0])


def test_real_gate_start_is_blocked_by_budget_and_missing_prior_promotion() -> None:
    ledger = AcceptanceLedger(identity=_identity())
    for ordinal in range(5):
        ledger = ledger.record_real_attempt(
            RealAttempt(
                attempt_id=f"real-{ordinal + 1}",
                run_id=f"run-{ordinal + 1}",
                stage_id="combat",
                outcome="failed",
                failure_code="REAL_GATE_FAILED",
                failure_layer="execution",
                occurred_at_ms=100 + ordinal,
            )
        )

    with pytest.raises(ValueError, match="PERFORM_OVERALL_ARCHITECTURE_AUDIT"):
        ledger.require_gate_start("R7")

    audited = ledger.record_architecture_audit(
        ArchitectureAudit(
            overall_failure_cause="Full-run retries hid the lowest failing boundary.",
            contributing_causes=("No cross-run stop line existed.",),
            systemic_changes=("Require lower-layer coverage before R8.",),
            evidence_refs=("artifact:architecture-audit",),
            recorded_at_ms=300,
        )
    )
    with pytest.raises(ValueError, match="PRIOR_GATE_NOT_PROMOTED"):
        audited.require_gate_start("R7")
