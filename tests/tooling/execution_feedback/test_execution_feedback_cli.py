from __future__ import annotations

from datetime import UTC, datetime

from tooling.execution_feedback import (
    CleanupStrategy,
    ExecutionPlanManifest,
    FeedbackStatus,
    FeedbackWindowResult,
    IterationPlanStore,
    LeaseDecision,
    LeaseManager,
    PlanStepSpec,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceObservation,
    ResourceOwnership,
)
from tooling.execution_feedback.cli import main, render_feedback_result

NOW = datetime(2026, 8, 8, tzinfo=UTC)


class FakeInspector:
    def __init__(self, identity: ResourceIdentity) -> None:
        self.identity = identity

    def inspect(self, _identity: ResourceIdentity) -> ResourceObservation:
        return ResourceObservation(identity=self.identity, running=True)


class FakeTerminator:
    def __init__(self) -> None:
        self.calls: list[tuple[ResourceIdentity, CleanupStrategy]] = []

    def terminate(self, identity: ResourceIdentity, strategy: CleanupStrategy) -> bool:
        self.calls.append((identity, strategy))
        return True


def _result(*, status: FeedbackStatus = FeedbackStatus.IN_PROGRESS) -> FeedbackWindowResult:
    return FeedbackWindowResult(
        run_id="run-one",
        step_id="build-step",
        window_sequence=1,
        status=status,
        started_at=NOW,
        feedback_at=NOW,
        elapsed_seconds=42,
        progress_summary="Build is still running",
        evidence_refs=("evidence:build-log",),
        lease=(
            ResourceLease(
                lease_id="build-lease",
                run_id="run-one",
                owner="worker-one",
                identity=ResourceIdentity(
                    kind=ResourceKind.PROCESS,
                    resource_id="123",
                    creation_token="start-one",
                ),
                command_digest="a" * 64,
                log_path="build.log",
                created_at=NOW,
                heartbeat_at=NOW,
                ttl_seconds=300,
                cleanup_strategy=CleanupStrategy.TERMINATE_PROCESS_GROUP,
            ).to_ref()
            if status is FeedbackStatus.IN_PROGRESS
            else None
        ),
        next_action="continue build-step",
    )


def test_concise_renderer_includes_safe_operator_fields() -> None:
    rendered = render_feedback_result(_result())

    assert "build-step" in rendered
    assert "42.0s" in rendered
    assert "in_progress" in rendered
    assert "evidence:build-log" in rendered
    assert "build-lease" in rendered
    assert "cancel --lease-id build-lease" in rendered
    assert "continue build-step" in rendered


def test_inspect_and_continue_persist_auditable_request(tmp_path, capsys) -> None:
    store = IterationPlanStore(tmp_path)
    store.write_plan(
        ExecutionPlanManifest(
            run_id="run-one",
            input_fingerprint="a" * 64,
            steps=(PlanStepSpec(id="build-step", action_kind="build"),),
        )
    )
    store.publish_result(_result())

    assert main(["--root", str(tmp_path), "inspect", "--run-id", "run-one"]) == 0
    assert "Build is still running" in capsys.readouterr().out
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "continue",
                "--run-id",
                "run-one",
                "--step-id",
                "build-step",
            ],
            now=lambda: NOW,
        )
        == 0
    )

    requests = store.list_continuation_requests("run-one")
    assert len(requests) == 1
    assert requests[0].step_id == "build-step"
    assert requests[0].requested_at == NOW


def test_continue_refuses_terminal_step(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    store.write_plan(
        ExecutionPlanManifest(
            run_id="run-one",
            input_fingerprint="a" * 64,
            steps=(PlanStepSpec(id="build-step", action_kind="build"),),
        )
    )
    store.publish_result(_result(status=FeedbackStatus.PASSED))

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "continue",
                "--run-id",
                "run-one",
                "--step-id",
                "build-step",
            ]
        )
        == 1
    )
    assert store.list_continuation_requests("run-one") == ()


def test_cancel_uses_lease_identity_and_never_a_name_or_port(tmp_path) -> None:
    identity = ResourceIdentity(
        kind=ResourceKind.PROCESS,
        resource_id="123",
        creation_token="start-one",
    )
    store = IterationPlanStore(tmp_path)
    LeaseManager(store).register(
        ResourceLease(
            lease_id="build-lease",
            run_id="run-one",
            owner="worker-one",
            identity=identity,
            command_digest="a" * 64,
            log_path="build.log",
            created_at=NOW,
            heartbeat_at=NOW,
            ttl_seconds=300,
            cleanup_strategy=CleanupStrategy.TERMINATE_PROCESS_GROUP,
            ownership=ResourceOwnership.OWNED,
        )
    )
    terminator = FakeTerminator()

    exit_code = main(
        ["--root", str(tmp_path), "cancel", "--lease-id", "build-lease"],
        inspector=FakeInspector(identity),
        terminator=terminator,
        now=lambda: NOW,
    )

    assert exit_code == 0
    assert terminator.calls == [(identity, CleanupStrategy.TERMINATE_PROCESS_GROUP)]
    assert LeaseManager(store).read("run-one", "build-lease").state.value == "cancelled"


def test_cancel_refuses_protected_external_resource(tmp_path) -> None:
    identity = ResourceIdentity(
        kind=ResourceKind.CONTAINER,
        resource_id="qwen-container-id",
        creation_token="started-at",
        project="qwen",
    )
    store = IterationPlanStore(tmp_path)
    LeaseManager(store).register(
        ResourceLease(
            lease_id="qwen-protected",
            run_id="run-one",
            owner="worker-one",
            identity=identity,
            command_digest="a" * 64,
            log_path="qwen.log",
            created_at=NOW,
            heartbeat_at=NOW,
            ttl_seconds=300,
            cleanup_strategy=CleanupStrategy.NONE,
            ownership=ResourceOwnership.PROTECTED_EXTERNAL,
        )
    )
    terminator = FakeTerminator()

    exit_code = main(
        ["--root", str(tmp_path), "cancel", "--lease-id", "qwen-protected"],
        inspector=FakeInspector(identity),
        terminator=terminator,
        now=lambda: NOW,
    )

    assert exit_code == 1
    assert terminator.calls == []
    inspection = LeaseManager(store).inspect(
        "qwen-protected",
        inspector=FakeInspector(identity),
        now=NOW,
    )
    assert inspection.decision is LeaseDecision.PROTECTED_EXTERNAL
