from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tooling.execution_feedback import (
    ActionResult,
    CheckpointRef,
    ExecutionPlanManifest,
    FeedbackBudget,
    FeedbackEventKind,
    FeedbackStatus,
    FeedbackWindowResult,
    IterationPlanStore,
    PlanStepSpec,
    supervise_feedback_window,
)


class ManualClock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.origin = datetime(2026, 8, 8, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.seconds

    def utc_now(self) -> datetime:
        return self.origin + timedelta(seconds=self.seconds)

    async def sleep(self, seconds: float) -> None:
        self.seconds += seconds
        await asyncio.sleep(0)


def _step(*, budget: FeedbackBudget | None = None) -> PlanStepSpec:
    return PlanStepSpec(
        id="bounded-step",
        action_kind="test",
        budget=budget or FeedbackBudget(),
    )


def test_default_budget_is_240_30_30_and_never_exceeds_five_minutes() -> None:
    budget = FeedbackBudget()

    assert budget.action_seconds == 240
    assert budget.evidence_seconds == 30
    assert budget.cleanup_seconds == 30
    assert budget.heartbeat_seconds == 60
    assert budget.deadline_seconds == 300

    with pytest.raises(ValidationError, match="must not exceed 300 seconds"):
        FeedbackBudget(action_seconds=241, evidence_seconds=30, cleanup_seconds=30)


def test_execution_plan_rejects_duplicate_and_unknown_step_dependencies() -> None:
    first = PlanStepSpec(id="first-step", action_kind="test")
    duplicate = PlanStepSpec(id="first-step", action_kind="test")
    unknown = PlanStepSpec(
        id="second-step",
        action_kind="test",
        depends_on=("missing-step",),
    )

    with pytest.raises(ValidationError, match="step IDs must be unique"):
        ExecutionPlanManifest(
            run_id="run-1",
            input_fingerprint="a" * 64,
            steps=(first, duplicate),
        )

    with pytest.raises(ValidationError, match="unknown step"):
        ExecutionPlanManifest(
            run_id="run-1",
            input_fingerprint="a" * 64,
            steps=(first, unknown),
        )


async def test_started_event_is_persisted_before_action_is_invoked(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    observed_kinds: list[FeedbackEventKind] = []

    async def action(_context) -> ActionResult:
        observed_kinds.extend(
            event.kind
            for event in store.list_events(
                run_id="run-1",
                step_id="bounded-step",
                window_sequence=1,
            )
        )
        return ActionResult.passed(progress_summary="complete")

    result = await supervise_feedback_window(
        run_id="run-1",
        step=_step(),
        window_sequence=1,
        store=store,
        action=action,
        clock=ManualClock(),
    )

    assert observed_kinds == [FeedbackEventKind.STARTED]
    assert result.status is FeedbackStatus.PASSED


async def test_threaded_short_action_does_not_wait_for_first_heartbeat(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)

    async def action(_context) -> ActionResult:
        return await asyncio.to_thread(
            ActionResult.passed,
            progress_summary="threaded command complete",
        )

    result = await asyncio.wait_for(
        supervise_feedback_window(
            run_id="threaded-short",
            step=_step(),
            window_sequence=1,
            store=store,
            action=action,
        ),
        timeout=2,
    )
    events = store.list_events(
        run_id="threaded-short",
        step_id="bounded-step",
        window_sequence=1,
    )

    assert result.status is FeedbackStatus.PASSED
    assert result.elapsed_seconds < 2
    assert [event.kind for event in events] == [FeedbackEventKind.STARTED]


async def test_hanging_action_and_cleanup_publish_by_300_simulated_seconds(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    never = asyncio.Event()

    async def action(context) -> ActionResult:
        context.set_phase("waiting-for-action")
        await never.wait()
        raise AssertionError("unreachable")

    async def capture_evidence(_context) -> tuple[str, ...]:
        await never.wait()
        raise AssertionError("unreachable")

    async def cleanup(_context) -> None:
        await never.wait()

    clock = ManualClock()
    result = await supervise_feedback_window(
        run_id="run-1",
        step=_step(),
        window_sequence=1,
        store=store,
        action=action,
        capture_evidence=capture_evidence,
        cleanup=cleanup,
        clock=clock,
    )

    events = store.list_events(
        run_id="run-1",
        step_id="bounded-step",
        window_sequence=1,
    )
    progress_elapsed = [
        event.elapsed_seconds for event in events if event.kind is FeedbackEventKind.PROGRESS
    ]

    assert progress_elapsed == [60, 120, 180, 240]
    assert result.status is FeedbackStatus.TIMED_OUT
    assert result.cleanup_pending is True
    assert result.elapsed_seconds == 300
    assert clock.monotonic() == 300
    assert store.read_result("run-1", "bounded-step", 1) == result


async def test_committed_checkpoint_turns_action_boundary_into_in_progress(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    never = asyncio.Event()

    async def action(context) -> ActionResult:
        context.commit_checkpoint(
            CheckpointRef(kind="mission", reference="mission:abc:transition:4")
        )
        context.set_phase("mission-running")
        await never.wait()
        raise AssertionError("unreachable")

    result = await supervise_feedback_window(
        run_id="run-2",
        step=_step(),
        window_sequence=3,
        store=store,
        action=action,
        clock=ManualClock(),
    )

    assert result.status is FeedbackStatus.IN_PROGRESS
    assert result.checkpoint == CheckpointRef(
        kind="mission",
        reference="mission:abc:transition:4",
    )
    assert result.next_action == "continue bounded-step from checkpoint"


def test_atomic_result_and_emitted_payload_use_the_same_model(tmp_path) -> None:
    store = IterationPlanStore(tmp_path)
    emitted: list[dict[str, object]] = []
    result = FeedbackWindowResult(
        run_id="run-1",
        step_id="bounded-step",
        window_sequence=1,
        status=FeedbackStatus.PASSED,
        started_at=datetime(2026, 8, 8, tzinfo=UTC),
        feedback_at=datetime(2026, 8, 8, 0, 0, 1, tzinfo=UTC),
        elapsed_seconds=1,
        progress_summary="complete",
        next_action="advance",
    )

    path = store.publish_result(result, emit=emitted.append)

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert emitted == [persisted]
    assert persisted == result.model_dump(mode="json")
    assert not tuple(tmp_path.rglob("*.tmp"))
