from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable, Coroutine
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol

from .models import (
    ActionResult,
    CheckpointRef,
    FeedbackEvent,
    FeedbackEventKind,
    FeedbackStatus,
    FeedbackWindowResult,
    PlanStepSpec,
    ResourceLeaseRef,
)
from .store import IterationPlanStore


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def utc_now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FeedbackContext:
    def __init__(self) -> None:
        self.phase = "running"
        self.checkpoint: CheckpointRef | None = None
        self.lease: ResourceLeaseRef | None = None
        self.evidence_refs: list[str] = []

    def set_phase(self, phase: str) -> None:
        normalized = phase.strip()
        if not normalized:
            raise ValueError("phase must not be empty")
        self.phase = normalized

    def commit_checkpoint(self, checkpoint: CheckpointRef) -> None:
        self.checkpoint = checkpoint

    def register_lease(self, lease: ResourceLeaseRef) -> None:
        self.lease = lease

    def add_evidence(self, *references: str) -> None:
        self.evidence_refs.extend(reference for reference in references if reference)

    @property
    def latest_evidence_ref(self) -> str | None:
        return self.evidence_refs[-1] if self.evidence_refs else None


async def _cancel_task[T](task: asyncio.Task[T]) -> None:
    if task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _wait_for_task_or_clock[T](
    task: asyncio.Task[T],
    *,
    seconds: float,
    clock: Clock,
) -> bool:
    """Return as soon as the work completes or the clock reaches the boundary."""
    sleeper = asyncio.create_task(clock.sleep(seconds))
    try:
        done, _ = await asyncio.wait(
            (task, sleeper),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done:
            return True
        sleeper.result()
        return task.done()
    finally:
        await _cancel_task(sleeper)


async def _run_phase[T](
    awaitable: Coroutine[Any, Any, T],
    *,
    budget_seconds: float,
    clock: Clock,
) -> tuple[bool, T | None]:
    task = asyncio.create_task(awaitable)
    await asyncio.sleep(0)
    if task.done():
        return True, task.result()
    completed = await _wait_for_task_or_clock(
        task,
        seconds=budget_seconds,
        clock=clock,
    )
    await asyncio.sleep(0)
    if completed or task.done():
        return True, task.result()
    await _cancel_task(task)
    return False, None


def _failure_fingerprint(step: PlanStepSpec, failure_kind: str) -> str:
    material = f"{step.id}:{step.action_kind}:{failure_kind}".encode()
    return hashlib.sha256(material).hexdigest()


async def supervise_feedback_window(
    *,
    run_id: str,
    step: PlanStepSpec,
    window_sequence: int,
    store: IterationPlanStore,
    action: Callable[[FeedbackContext], Coroutine[Any, Any, ActionResult]],
    clock: Clock | None = None,
    capture_evidence: Callable[[FeedbackContext], Coroutine[Any, Any, tuple[str, ...]]]
    | None = None,
    cleanup: Callable[[FeedbackContext], Coroutine[Any, Any, None]] | None = None,
    emit: Callable[[dict[str, object]], None] | None = None,
) -> FeedbackWindowResult:
    active_clock = clock or SystemClock()
    context = FeedbackContext()
    started_monotonic = active_clock.monotonic()
    started_at = active_clock.utc_now()
    store.write_event(
        FeedbackEvent(
            run_id=run_id,
            step_id=step.id,
            window_sequence=window_sequence,
            kind=FeedbackEventKind.STARTED,
            emitted_at=started_at,
            elapsed_seconds=0,
            phase="started",
        )
    )

    action_task = asyncio.create_task(action(context))
    await asyncio.sleep(0)
    next_heartbeat = step.budget.heartbeat_seconds
    action_deadline = step.budget.action_seconds
    action_result: ActionResult | None = None
    action_failure: BaseException | None = None

    while not action_task.done() and active_clock.monotonic() - started_monotonic < action_deadline:
        elapsed = active_clock.monotonic() - started_monotonic
        wake_at = min(next_heartbeat, action_deadline)
        action_completed = await _wait_for_task_or_clock(
            action_task,
            seconds=max(0, wake_at - elapsed),
            clock=active_clock,
        )
        await asyncio.sleep(0)
        if action_completed:
            break
        elapsed = active_clock.monotonic() - started_monotonic
        if elapsed >= next_heartbeat:
            store.write_event(
                FeedbackEvent(
                    run_id=run_id,
                    step_id=step.id,
                    window_sequence=window_sequence,
                    kind=FeedbackEventKind.PROGRESS,
                    emitted_at=active_clock.utc_now(),
                    elapsed_seconds=elapsed,
                    phase=context.phase,
                    evidence_ref=context.latest_evidence_ref,
                )
            )
            next_heartbeat += step.budget.heartbeat_seconds

    if action_task.done():
        try:
            action_result = action_task.result()
        except BaseException as exc:  # noqa: BLE001 - converted into typed evidence
            action_failure = exc
    else:
        await _cancel_task(action_task)

    evidence_timed_out = False
    if capture_evidence is not None:
        evidence_completed, evidence_refs = await _run_phase(
            capture_evidence(context),
            budget_seconds=step.budget.evidence_seconds,
            clock=active_clock,
        )
        evidence_timed_out = not evidence_completed
        if evidence_refs:
            context.add_evidence(*evidence_refs)

    cleanup_pending = False
    if cleanup is not None:
        cleanup_completed, _ = await _run_phase(
            cleanup(context),
            budget_seconds=step.budget.cleanup_seconds,
            clock=active_clock,
        )
        cleanup_pending = not cleanup_completed

    if action_result is not None:
        status = action_result.status
        progress_summary = action_result.progress_summary
        checkpoint = action_result.checkpoint or context.checkpoint
        lease = action_result.lease or context.lease
        failure_fingerprint = action_result.failure_fingerprint
        next_action = action_result.next_action
        context.add_evidence(*action_result.evidence_refs)
    elif action_failure is not None:
        status = FeedbackStatus.FAILED
        progress_summary = f"action raised {type(action_failure).__name__}: {action_failure}"
        checkpoint = context.checkpoint
        lease = context.lease
        failure_fingerprint = _failure_fingerprint(step, type(action_failure).__name__)
        next_action = f"inspect {step.id} failure"
    elif context.checkpoint is not None or context.lease is not None:
        status = FeedbackStatus.IN_PROGRESS
        progress_summary = f"{step.id} reached its action boundary with resumable state"
        checkpoint = context.checkpoint
        lease = context.lease
        failure_fingerprint = None
        next_action = f"continue {step.id} from checkpoint"
    else:
        status = FeedbackStatus.TIMED_OUT
        progress_summary = f"{step.id} exceeded its action budget"
        checkpoint = None
        lease = None
        failure_fingerprint = _failure_fingerprint(step, "action-timeout")
        next_action = f"inspect {step.id} timeout"

    if evidence_timed_out:
        progress_summary = f"{progress_summary}; evidence capture timed out"

    result = FeedbackWindowResult(
        run_id=run_id,
        step_id=step.id,
        window_sequence=window_sequence,
        status=status,
        started_at=started_at,
        feedback_at=active_clock.utc_now(),
        elapsed_seconds=active_clock.monotonic() - started_monotonic,
        progress_summary=progress_summary,
        evidence_refs=tuple(dict.fromkeys(context.evidence_refs)),
        checkpoint=checkpoint,
        lease=lease,
        failure_fingerprint=failure_fingerprint,
        next_action=next_action,
        cleanup_pending=cleanup_pending,
    )
    store.publish_result(result, emit=emit)
    return result
