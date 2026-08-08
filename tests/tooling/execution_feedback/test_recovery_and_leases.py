from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from tooling.execution_feedback import (
    CleanupStrategy,
    FeedbackStatus,
    FeedbackWindowResult,
    IterationPlanStore,
    LeaseDecision,
    LeaseManager,
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceObservation,
    ResourceOwnership,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _result(*, window_sequence: int = 1) -> FeedbackWindowResult:
    return FeedbackWindowResult(
        run_id="run-1",
        step_id="bounded-step",
        window_sequence=window_sequence,
        status=FeedbackStatus.PASSED,
        started_at=NOW,
        feedback_at=NOW + timedelta(seconds=1),
        elapsed_seconds=1,
        progress_summary="complete",
        next_action="advance",
    )


def _result_path(root: Path, window_sequence: int) -> Path:
    return (
        root
        / "run-1"
        / "steps"
        / "bounded-step"
        / "windows"
        / f"{window_sequence:06d}"
        / "result.json"
    )


def _lease(
    lease_id: str,
    *,
    kind: ResourceKind = ResourceKind.PROCESS,
    resource_id: str = "1234",
    creation_token: str = "started-a",
    ownership: ResourceOwnership = ResourceOwnership.OWNED,
) -> ResourceLease:
    cleanup = (
        CleanupStrategy.NONE
        if ownership is ResourceOwnership.PROTECTED_EXTERNAL
        else (
            CleanupStrategy.TERMINATE_PROCESS_GROUP
            if kind is ResourceKind.PROCESS
            else CleanupStrategy.STOP_CONTAINER
        )
    )
    return ResourceLease(
        lease_id=lease_id,
        run_id="run-1",
        owner="worker-a",
        identity=ResourceIdentity(
            kind=kind,
            resource_id=resource_id,
            creation_token=creation_token,
            project="animetta" if kind is ResourceKind.CONTAINER else None,
        ),
        command_digest="b" * 64,
        log_path="artifacts/iteration-plans/run-1/logs/resource.log",
        created_at=NOW,
        heartbeat_at=NOW,
        ttl_seconds=60,
        cleanup_strategy=cleanup,
        ownership=ownership,
    )


class FakeInspector:
    def __init__(self, observations: dict[tuple[ResourceKind, str], ResourceObservation]) -> None:
        self.observations = observations
        self.requested: list[ResourceIdentity] = []

    def inspect(self, identity: ResourceIdentity) -> ResourceObservation:
        self.requested.append(identity)
        return self.observations[(identity.kind, identity.resource_id)]


class FakeTerminator:
    def __init__(self, *, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.calls: list[tuple[ResourceIdentity, CleanupStrategy]] = []

    def terminate(self, identity: ResourceIdentity, strategy: CleanupStrategy) -> bool:
        self.calls.append((identity, strategy))
        return self.succeeds


def _observation(
    lease: ResourceLease,
    *,
    creation_token: str | None = None,
    running: bool = True,
) -> ResourceObservation:
    return ResourceObservation(
        identity=lease.identity.model_copy(
            update={"creation_token": creation_token or lease.identity.creation_token}
        ),
        running=running,
        exit_code=None if running else 0,
    )


def test_recovery_skips_corrupt_and_partial_results(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    valid = _result(window_sequence=1)
    store.publish_result(valid)
    corrupt = _result_path(tmp_path, 2)
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text('{"schema_version": 1, "status": ', encoding="utf-8")
    partial = _result_path(tmp_path, 3).with_suffix(".json.partial.tmp")
    partial.parent.mkdir(parents=True)
    partial.write_text(_result(window_sequence=3).model_dump_json(), encoding="utf-8")

    recovery = store.recover_latest_result("run-1", "bounded-step")

    assert recovery.result == valid
    assert recovery.rejected_artifacts == (corrupt.resolve().as_posix(),)
    assert recovery.latest_window_sequence == 1


def test_recovery_rejects_incompatible_schema_instead_of_using_it(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    path = _result_path(tmp_path, 1)
    path.parent.mkdir(parents=True)
    payload = _result().model_dump(mode="json")
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")

    recovery = store.recover_latest_result("run-1", "bounded-step")

    assert recovery.result is None
    assert recovery.latest_window_sequence is None
    assert recovery.rejected_artifacts == (path.resolve().as_posix(),)


def test_persistent_lease_expires_without_heartbeat(tmp_path) -> None:
    manager = LeaseManager(IterationPlanStore(tmp_path))
    lease = _lease("process-lease")
    manager.register(lease)
    inspector = FakeInspector({(ResourceKind.PROCESS, "1234"): _observation(lease)})

    active = manager.inspect(
        lease.lease_id,
        inspector=inspector,
        now=NOW + timedelta(seconds=59),
    )
    expired = manager.inspect(
        lease.lease_id,
        inspector=inspector,
        now=NOW + timedelta(seconds=61),
    )

    assert manager.read(lease.run_id, lease.lease_id) == lease
    assert active.decision is LeaseDecision.MATCHING
    assert active.authority_to_terminate is True
    assert expired.decision is LeaseDecision.EXPIRED
    assert expired.authority_to_terminate is False


def test_heartbeat_renews_ttl_and_revalidates_owner_and_timestamp(tmp_path) -> None:
    manager = LeaseManager(IterationPlanStore(tmp_path))
    lease = _lease("process-lease")
    manager.register(lease)
    inspector = FakeInspector({(ResourceKind.PROCESS, "1234"): _observation(lease)})

    renewed = manager.heartbeat(
        lease.lease_id,
        owner="worker-a",
        now=NOW + timedelta(seconds=50),
    )

    assert renewed.heartbeat_at == NOW + timedelta(seconds=50)
    assert (
        manager.inspect(
            lease.lease_id,
            inspector=inspector,
            now=NOW + timedelta(seconds=109),
        ).decision
        is LeaseDecision.MATCHING
    )
    with pytest.raises(PermissionError, match="owner does not match"):
        manager.heartbeat(
            lease.lease_id,
            owner="worker-b",
            now=NOW + timedelta(seconds=51),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        manager.heartbeat(
            lease.lease_id,
            owner="worker-a",
            now=datetime(2026, 8, 8),
        )


def test_pid_creation_token_reuse_refuses_termination(tmp_path) -> None:
    manager = LeaseManager(IterationPlanStore(tmp_path))
    lease = _lease("process-lease")
    manager.register(lease)
    inspector = FakeInspector(
        {
            (ResourceKind.PROCESS, "1234"): _observation(
                lease,
                creation_token="started-by-someone-else",
            )
        }
    )
    terminator = FakeTerminator()

    outcome = manager.cancel(
        lease.lease_id,
        inspector=inspector,
        terminator=terminator,
        now=NOW + timedelta(seconds=1),
    )

    assert outcome.decision is LeaseDecision.IDENTITY_MISMATCH
    assert outcome.authority_to_terminate is False
    assert terminator.calls == []


def test_container_started_at_drift_refuses_termination(tmp_path) -> None:
    manager = LeaseManager(IterationPlanStore(tmp_path))
    lease = _lease(
        "container-lease",
        kind=ResourceKind.CONTAINER,
        resource_id="container-a",
        creation_token="2026-08-08T01:00:00Z",
    )
    manager.register(lease)
    inspector = FakeInspector(
        {
            (ResourceKind.CONTAINER, "container-a"): _observation(
                lease,
                creation_token="2026-08-08T02:00:00Z",
            )
        }
    )
    terminator = FakeTerminator()

    outcome = manager.cancel(
        lease.lease_id,
        inspector=inspector,
        terminator=terminator,
        now=NOW + timedelta(seconds=1),
    )

    assert outcome.decision is LeaseDecision.IDENTITY_MISMATCH
    assert terminator.calls == []


def test_protected_external_resource_is_never_cancelled(tmp_path) -> None:
    manager = LeaseManager(IterationPlanStore(tmp_path))
    lease = _lease(
        "protected-client",
        ownership=ResourceOwnership.PROTECTED_EXTERNAL,
    )
    manager.register(lease)
    inspector = FakeInspector({(ResourceKind.PROCESS, "1234"): _observation(lease)})
    terminator = FakeTerminator()

    outcome = manager.cancel(
        lease.lease_id,
        inspector=inspector,
        terminator=terminator,
        now=NOW + timedelta(seconds=1),
    )

    assert outcome.decision is LeaseDecision.PROTECTED_EXTERNAL
    assert terminator.calls == []


def test_matching_owned_resource_is_cancelled_by_exact_identity(tmp_path) -> None:
    manager = LeaseManager(IterationPlanStore(tmp_path))
    lease = _lease("process-lease")
    manager.register(lease)
    inspector = FakeInspector({(ResourceKind.PROCESS, "1234"): _observation(lease)})
    terminator = FakeTerminator()

    outcome = manager.cancel(
        lease.lease_id,
        inspector=inspector,
        terminator=terminator,
        now=NOW + timedelta(seconds=1),
    )

    assert outcome.decision is LeaseDecision.CANCELLED
    assert terminator.calls == [(lease.identity, lease.cleanup_strategy)]
    assert manager.read(lease.run_id, lease.lease_id).state is LeaseState.CANCELLED


def test_reconcile_takes_over_matches_and_quarantines_identity_drift(tmp_path) -> None:
    manager = LeaseManager(IterationPlanStore(tmp_path))
    running = _lease("running-lease", resource_id="100")
    completed = _lease("completed-lease", resource_id="200")
    drifted = _lease("drifted-lease", resource_id="300")
    for lease in (running, completed, drifted):
        manager.register(lease)
    inspector = FakeInspector(
        {
            (ResourceKind.PROCESS, "100"): _observation(running),
            (ResourceKind.PROCESS, "200"): _observation(completed, running=False),
            (ResourceKind.PROCESS, "300"): _observation(
                drifted,
                creation_token="reused-process",
            ),
        }
    )

    outcomes = manager.reconcile(
        run_id="run-1",
        inspector=inspector,
        new_owner="worker-b",
        now=NOW + timedelta(seconds=61),
    )
    by_id = {outcome.lease.lease_id: outcome for outcome in outcomes}

    assert by_id["running-lease"].decision is LeaseDecision.TAKEN_OVER
    assert by_id["running-lease"].lease.owner == "worker-b"
    assert by_id["completed-lease"].decision is LeaseDecision.COMPLETED
    assert by_id["completed-lease"].lease.state is LeaseState.COMPLETED
    assert by_id["drifted-lease"].decision is LeaseDecision.IDENTITY_MISMATCH
    assert by_id["drifted-lease"].lease.state is LeaseState.ORPHANED_WITHOUT_AUTHORITY
