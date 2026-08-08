"""Bounded FIFO scheduler and durable global stop-barrier races."""

from __future__ import annotations

import asyncio

import pytest

from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.journal import (
    CommandDraft,
    InMemoryCommandJournal,
    QueueCapacityExceededError,
)
from animetta.tools.minecraft.voyager.scheduler import (
    CommandExecutionError,
    VoyagerCommandScheduler,
)
from animetta.tools.minecraft.voyager.stop import GlobalStopBarrier


def draft(index: int, *, deadline: int = 10_000) -> CommandDraft:
    return CommandDraft(
        command_id=f"command-{index}",
        caller_scope="principal:a",
        request_id=f"request-{index}",
        request_hash=f"{index:x}" * 64,
        kind="execute",
        mode="atomic",
        payload={"index": index},
        requested_budget={},
        effective_budget={},
        accepted_at_ms=index,
        queue_deadline_ms=deadline,
    )


async def test_scheduler_is_fifo_single_consumer_and_bounded() -> None:
    repository = InMemoryCommandJournal(queue_capacity=3)
    active = 0
    maximum_active = 0
    order: list[str] = []

    async def consume(command) -> None:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        order.append(command.command_id)
        await asyncio.sleep(0.005)
        active -= 1

    scheduler = VoyagerCommandScheduler(repository=repository, consumer=consume, now_ms=lambda: 100)
    for index in range(3):
        await repository.create_command(draft(index))
    with pytest.raises(QueueCapacityExceededError):
        await repository.create_command(draft(3))

    await asyncio.gather(*(scheduler.run_once() for _ in range(6)))

    assert order == ["command-0", "command-1", "command-2"]
    assert maximum_active == 1


async def test_queue_deadline_and_dispatch_race_has_one_cas_winner() -> None:
    repository = InMemoryCommandJournal()
    command, _ = await repository.create_command(draft(1, deadline=100))
    consumed: list[str] = []
    scheduler = VoyagerCommandScheduler(
        repository=repository,
        consumer=lambda item: _append(consumed, item.command_id),
        now_ms=lambda: 100,
    )

    await asyncio.gather(scheduler.run_once(), scheduler.expire_queued())

    final = await repository.get_command(command.command_id)
    assert final is not None and final.state is CommandState.FAILED
    assert consumed == []


async def _append(target: list[str], value: str) -> None:
    target.append(value)


async def test_stop_barrier_cancels_pending_blocks_admission_and_signals_active_once() -> None:
    repository = InMemoryCommandJournal()
    active, _ = await repository.create_command(draft(1))
    pending, _ = await repository.create_command(draft(2))
    active = await repository.transition(
        active.command_id,
        expected_version=0,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="worker",
        occurred_at_ms=20,
    )
    signals: list[str] = []
    barrier = GlobalStopBarrier(
        repository=repository,
        signal_active=lambda command_id: _append(signals, command_id),
        now_ms=lambda: 30,
    )

    first = await barrier.stop(
        caller_scope="principal:a", request_id="stop-1", reason="operator stop"
    )
    repeated = await barrier.stop(
        caller_scope="principal:a", request_id="stop-1", reason="operator stop"
    )

    assert first.stop_command_id == repeated.stop_command_id
    assert repeated.idempotency_reused is True
    assert (
        await repository.get_command(pending.command_id)
    ).state is CommandState.CANCELLED_BY_STOP
    assert (await repository.get_command(active.command_id)).cancel_requested_at_ms == 30
    assert signals == [active.command_id]
    with pytest.raises(RuntimeError, match="NOT_ACCEPTING"):
        await repository.create_command(draft(3))


async def test_stop_without_active_work_commits_its_own_terminal_outcome() -> None:
    repository = InMemoryCommandJournal()
    barrier = GlobalStopBarrier(
        repository=repository,
        signal_active=lambda command_id: _append([], command_id),
        now_ms=lambda: 30,
    )

    result = await barrier.stop(
        caller_scope="principal:a", request_id="stop-idle", reason="operator stop"
    )

    command = await repository.get_command(result.stop_command_id)
    assert command is not None and command.state is CommandState.SUCCEEDED
    assert result.recovery_error is None


async def test_unknown_consumer_outcome_commits_reconciliation_then_quarantine() -> None:
    repository = InMemoryCommandJournal()
    await repository.create_command(draft(1))

    async def consume(_command) -> None:
        raise CommandExecutionError(
            terminal_state=CommandState.BLOCKED_UNKNOWN,
            reason_code="RUNTIME_RESPONSE_LOST",
            message="response lost after possible mutation",
            requires_reconciliation=True,
        )

    scheduler = VoyagerCommandScheduler(repository=repository, consumer=consume, now_ms=lambda: 100)
    await scheduler.run_once()

    command = await repository.get_command("command-1")
    transitions = await repository.transitions("command-1")
    assert command is not None and command.state is CommandState.BLOCKED_UNKNOWN
    assert [item.to_state for item in transitions][-2:] == [
        "reconciling",
        "blocked_unknown",
    ]


async def test_scheduler_atomically_persists_controller_terminal_result() -> None:
    repository = InMemoryCommandJournal()
    await repository.create_command(draft(1))
    terminal_result = {
        "command_id": "command-1",
        "state": "failed",
        "output": {"verification": {"satisfied": False}},
        "receipt_ids": [],
        "learning_evidence_eligible": False,
        "error": None,
    }

    async def consume(_command) -> None:
        raise CommandExecutionError(
            terminal_state=CommandState.FAILED,
            reason_code="GOAL_VERIFICATION_FAILED",
            message="independent goal verification failed",
            terminal_result=terminal_result,
        )

    scheduler = VoyagerCommandScheduler(repository=repository, consumer=consume, now_ms=lambda: 100)
    await scheduler.run_once()

    command = await repository.get_command("command-1")
    assert command is not None
    assert command.state is CommandState.FAILED
    assert command.terminal_result == terminal_result
