from __future__ import annotations

from datetime import UTC, datetime

from tooling.execution_feedback import FeedbackStatus
from tooling.execution_feedback.minecraft import (
    FallbackReceipt,
    MinecraftActionRequest,
    MissionCheckpointStore,
    MissionWindowAdapter,
    MissionWindowSnapshot,
    MissionWindowStatus,
    ViewerReadinessAdapter,
    aggregate_minecraft_stages,
    boundary_admission,
    build_r7_feedback_plan,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)


class VirtualClock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def monotonic(self) -> float:
        return self.elapsed

    async def sleep(self, seconds: float) -> None:
        self.elapsed += seconds


class FakeViewerBridge:
    def __init__(self, *, ready_after: int) -> None:
        self.ready_after = ready_after
        self.status_calls = 0
        self.capture_calls = 0
        self.calls: list[str] = []

    async def binding_status(self) -> tuple[bool, str]:
        self.calls.append("binding_status")
        self.status_calls += 1
        return self.status_calls >= self.ready_after, f"binding:{self.status_calls}"

    async def capture(self) -> str:
        self.calls.append("capture")
        self.capture_calls += 1
        return "capture:viewer"


class FakeMissionRepository:
    def __init__(self, snapshot: MissionWindowSnapshot) -> None:
        self.value = snapshot
        self.snapshot_calls = 0
        self.submissions = 0

    async def snapshot(self, mission_id: str) -> MissionWindowSnapshot:
        assert mission_id == self.value.mission_id
        self.snapshot_calls += 1
        return self.value


async def test_viewer_readiness_uses_only_binding_and_capture_and_returns_bounded_feedback() -> (
    None
):
    bridge = FakeViewerBridge(ready_after=3)
    clock = VirtualClock()

    result = await ViewerReadinessAdapter(bridge, clock=clock).wait_ready()

    assert result.status is FeedbackStatus.PASSED
    assert result.evidence_refs == ("binding:3", "capture:viewer")
    assert clock.elapsed == 60
    assert set(bridge.calls) == {"binding_status", "capture"}
    assert bridge.capture_calls == 1


async def test_viewer_timeout_never_attempts_to_control_or_restart_minecraft() -> None:
    bridge = FakeViewerBridge(ready_after=99)
    clock = VirtualClock()

    result = await ViewerReadinessAdapter(bridge, clock=clock).wait_ready()

    assert result.status is FeedbackStatus.TIMED_OUT
    assert clock.elapsed == 240
    assert bridge.capture_calls == 0
    assert set(bridge.calls) == {"binding_status"}


def test_r7_plan_splits_viewer_each_combat_target_and_every_acceptance_stage() -> None:
    plan = build_r7_feedback_plan(run_id="r7-run", input_fingerprint="a" * 64)

    assert tuple(step.id for step in plan.steps) == (
        "viewer-readiness",
        "combat-zombie",
        "combat-skeleton",
        "combat-spider",
        "construction",
        "learning",
        "independent-validation",
        "trusted-reuse",
        "projection",
        "ledger-settlement",
    )
    assert all(step.budget.deadline_seconds <= 300 for step in plan.steps)


async def test_r8_snapshot_is_checkpointed_without_submitting_a_duplicate_mission(
    tmp_path,
) -> None:
    snapshot = MissionWindowSnapshot(
        mission_id="mission-one",
        status=MissionWindowStatus.RUNNING,
        transition_sequence=7,
        objective_reference="objective:build-house:v2",
        budget_reference="budget:usage:4",
        receipt_reference="receipt:command:9",
        world_state_reference="world-state:12",
        advancement_reference="advancement:adventure-root",
        skill_version_reference="skill:house:v3",
        captured_at=NOW,
    )
    repository = FakeMissionRepository(snapshot)
    store = MissionCheckpointStore(tmp_path)

    result = await MissionWindowAdapter(repository, store=store).capture("mission-one")

    assert result.status is FeedbackStatus.IN_PROGRESS
    assert result.checkpoint is not None
    assert store.read("mission-one") == snapshot
    assert repository.snapshot_calls == 1
    assert repository.submissions == 0


def test_action_boundary_allows_only_safety_and_fallback_receipt_is_not_completion() -> None:
    ordinary = boundary_admission(
        MinecraftActionRequest(action_id="mine-iron", safety_action=False),
        action_boundary_reached=True,
    )
    safety = boundary_admission(
        MinecraftActionRequest(action_id="retreat-hostile", safety_action=True),
        action_boundary_reached=True,
    )
    receipt = FallbackReceipt(
        receipt_id="fallback-one",
        action_id="retreat-hostile",
        evidence_reference="receipt:safety:1",
    )

    assert ordinary.allowed is False
    assert safety.allowed is True
    assert receipt.safety_only is True
    assert receipt.can_satisfy_objective is False


def test_r7_r8_aggregate_passes_only_when_every_required_stage_passes() -> None:
    plan = build_r7_feedback_plan(run_id="r7-run", input_fingerprint="a" * 64)
    partial = aggregate_minecraft_stages(
        plan,
        {step.id: FeedbackStatus.PASSED for step in plan.steps[:-1]},
    )
    complete = aggregate_minecraft_stages(
        plan,
        {step.id: FeedbackStatus.PASSED for step in plan.steps},
    )

    assert partial.status.value == "in_progress"
    assert partial.nonpassing_required_steps == ("ledger-settlement",)
    assert complete.status.value == "passed"
