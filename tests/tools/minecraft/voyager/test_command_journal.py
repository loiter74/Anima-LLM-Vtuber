"""Repository contract tests for durable commands, facts, and projections."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.journal import (
    CommandDraft,
    IdempotencyConflictError,
    InMemoryCommandJournal,
    QueueCapacityExceededError,
    StaleCommandVersionError,
    StepRecord,
)
from animetta.tools.minecraft.voyager.sqlite_repository import SQLiteCommandJournal


def draft(request_id: str, request_hash: str, *, caller: str = "principal:a") -> CommandDraft:
    return CommandDraft(
        command_id=f"command-{request_id}",
        caller_scope=caller,
        request_id=request_id,
        request_hash=request_hash,
        kind="execute",
        mode="atomic",
        payload={"action": {"capability": "observe", "parameters": {}}},
        requested_budget={},
        effective_budget={"max_actions": 1},
        accepted_at_ms=100,
        queue_deadline_ms=1_000,
    )


def persisted_budget(path, command_id: str) -> tuple[int, dict, dict]:
    with sqlite3.connect(path) as db:
        row = db.execute(
            """SELECT usage_version,settled_usage_json,reserved_usage_json
            FROM command_budget_usage WHERE command_id=?""",
            (command_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]), json.loads(row[1]), json.loads(row[2])


def persisted_settled_at(path, step_id: str) -> int | None:
    with sqlite3.connect(path) as db:
        row = db.execute(
            "SELECT settled_at_ms FROM command_steps WHERE step_id=?",
            (step_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]) if row[0] is not None else None


@pytest.mark.parametrize("factory", [InMemoryCommandJournal])
async def test_sequence_idempotency_cas_and_append_only_facts(factory) -> None:
    repository = factory()
    first, reused = await repository.create_command(draft("one", "a" * 64))
    same, reused_same = await repository.create_command(draft("one", "a" * 64))
    second, _ = await repository.create_command(draft("two", "b" * 64))

    assert reused is False
    assert reused_same is True and same.command_id == first.command_id
    assert second.queue_sequence == first.queue_sequence + 1
    with pytest.raises(IdempotencyConflictError):
        await repository.create_command(draft("one", "c" * 64))

    running = await repository.transition(
        first.command_id,
        expected_version=first.state_version,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="worker",
        occurred_at_ms=110,
    )
    with pytest.raises(StaleCommandVersionError):
        await repository.transition(
            first.command_id,
            expected_version=first.state_version,
            target=CommandState.FAILED,
            reason_code="STALE",
            actor="test",
            occurred_at_ms=111,
        )
    await repository.append_receipt(first.command_id, 1, {"receipt_id": "receipt-1"})
    await repository.save_budget(first.command_id, {"max_actions": 1}, {})
    await repository.append_checkpoint(first.command_id, {"checkpoint_id": "checkpoint-1"})
    await repository.append_recovery(first.command_id, {"recovery_id": "recovery-1"})

    transitions = await repository.transitions(first.command_id)
    facts = await repository.command_facts(first.command_id)
    assert [item.to_state for item in transitions] == ["queued", "running"]
    assert running.state_version == 1
    assert facts == {"receipts": 1, "budgets": 1, "checkpoints": 1, "recoveries": 1}


async def test_concurrent_idempotency_creates_exactly_one_command() -> None:
    repository = InMemoryCommandJournal()
    results = await asyncio.gather(
        *(repository.create_command(draft("same", "a" * 64)) for _ in range(20))
    )

    assert len({result[0].command_id for result in results}) == 1
    assert sum(not reused for _, reused in results) == 1


async def test_startup_recovery_never_replays_unfinished_commands() -> None:
    repository = InMemoryCommandJournal()
    queued, _ = await repository.create_command(draft("queued", "a" * 64))
    active, _ = await repository.create_command(draft("active", "b" * 64))
    await repository.transition(
        active.command_id,
        expected_version=0,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="worker",
        occurred_at_ms=110,
    )

    result = await repository.recover_startup(occurred_at_ms=200)

    assert result.quarantined is True
    assert (
        await repository.get_command(queued.command_id)
    ).state is CommandState.INTERRUPTED_BEFORE_START
    assert (await repository.get_command(active.command_id)).state is CommandState.BLOCKED_UNKNOWN
    assert await repository.next_eligible(now_ms=200) is None


async def test_projection_reads_are_scope_isolated_paginated_and_runtime_free() -> None:
    repository = InMemoryCommandJournal()
    for index in range(5):
        await repository.create_command(draft(str(index), f"{index}" * 64, caller="principal:a"))
    await repository.create_command(draft("private", "f" * 64, caller="principal:b"))

    page = await repository.read_projection("principal:a", limit=2)
    next_page = await repository.read_projection("principal:a", limit=2, cursor=page.next_cursor)

    assert len(page.commands) == 2
    assert len(next_page.commands) == 2
    assert all(command.caller_scope == "principal:a" for command in page.commands)
    assert page.projection_version >= 6
    assert await repository.find_by_request("principal:a", "private") is None


async def test_sqlite_journal_migrations_pragmas_indexes_and_tombstone_retention(
    tmp_path,
) -> None:
    path = tmp_path / "journal.db"
    repository = SQLiteCommandJournal(path)
    await repository.connect()
    try:
        command, _ = await repository.create_command(draft("one", "a" * 64))
        await repository.transition(
            command.command_id,
            expected_version=0,
            target=CommandState.RUNNING,
            reason_code="DISPATCHED",
            actor="worker",
            occurred_at_ms=110,
        )
        await repository.transition(
            command.command_id,
            expected_version=1,
            target=CommandState.SUCCEEDED,
            reason_code="VERIFIED",
            actor="controller",
            occurred_at_ms=120,
        )
        await repository.expire_terminal_payloads(before_ms=1_000)
        pragmas = await repository.pragmas()
        indexes = await repository.index_names()
    finally:
        await repository.close()

    reopened = SQLiteCommandJournal(path)
    await reopened.connect()
    try:
        with pytest.raises(IdempotencyConflictError):
            await reopened.create_command(draft("one", "b" * 64))
        original, reused = await reopened.create_command(draft("one", "a" * 64))
    finally:
        await reopened.close()

    assert reused is True and original.command_id == "command-one"
    assert pragmas["journal_mode"] == "wal"
    assert pragmas["foreign_keys"] == 1
    assert pragmas["busy_timeout"] == 5_000
    assert {"idx_commands_state_sequence", "idx_transitions_command_id"}.issubset(indexes)


async def test_sqlite_queue_capacity_is_enforced_inside_admission_transaction(
    tmp_path,
) -> None:
    repository = SQLiteCommandJournal(tmp_path / "bounded.db", queue_capacity=1)
    await repository.connect()
    try:
        await repository.create_command(draft("one", "a" * 64))
        with pytest.raises(QueueCapacityExceededError):
            await repository.create_command(draft("two", "b" * 64))
    finally:
        await repository.close()


async def test_sqlite_terminal_transition_persists_structured_result(tmp_path) -> None:
    path = tmp_path / "terminal-result.db"
    terminal_result = {
        "command_id": "command-result",
        "state": "failed",
        "output": {"goal_verification": {"satisfied": False}},
        "receipt_ids": ["receipt-1"],
        "learning_evidence_eligible": False,
        "error": {"code": "GOAL_VERIFICATION_FAILED"},
    }
    repository = SQLiteCommandJournal(path)
    await repository.connect()
    command, _ = await repository.create_command(draft("result", "c" * 64))
    running = await repository.transition(
        command.command_id,
        expected_version=0,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="worker",
        occurred_at_ms=110,
    )
    await repository.transition(
        running.command_id,
        expected_version=running.state_version,
        target=CommandState.FAILED,
        reason_code="GOAL_VERIFICATION_FAILED",
        actor="controller",
        occurred_at_ms=120,
        terminal_result=terminal_result,
    )
    await repository.close()

    reopened = SQLiteCommandJournal(path)
    await reopened.connect()
    try:
        persisted = await reopened.get_command(command.command_id)
    finally:
        await reopened.close()

    assert persisted is not None
    assert persisted.terminal_result == terminal_result


async def test_sqlite_generates_internal_checkpoint_and_recovery_ids(tmp_path) -> None:
    repository = SQLiteCommandJournal(tmp_path / "facts.db")
    await repository.connect()
    try:
        command, _ = await repository.create_command(draft("facts", "a" * 64))

        await repository.append_checkpoint(command.command_id, {"step_id": "step-1"})
        await repository.append_recovery(command.command_id, {"decision": "blocked_unknown"})

        facts = await repository.command_facts(command.command_id)
    finally:
        await repository.close()

    assert facts["checkpoints"] == 1
    assert facts["recoveries"] == 1


async def test_sqlite_retains_unknown_receipt_and_settles_it_once(tmp_path) -> None:
    repository = SQLiteCommandJournal(tmp_path / "pending-receipt.db")
    await repository.connect()
    try:
        command, _ = await repository.create_command(draft("pending", "d" * 64))
        step = StepRecord(
            step_id="step-pending",
            command_id=command.command_id,
            ordinal=1,
            strategy_state_hash="a" * 64,
            capability="attack",
            params_hash="b" * 64,
            params={"target": "zombie"},
            correlation_id="correlation-pending",
            runtime_instance_id="runtime-pending",
            state="reserved",
            reservation={"max_actions": 1},
            before_observation_hash="c" * 64,
        )
        receipt = {
            "receipt_id": "receipt-pending",
            "content_hash": "e" * 64,
            "outcome": "success",
            "finished_at_ms": 1_800_000_000_123,
        }
        await repository.reserve_step(step)
        await repository.update_step_state(step.step_id, "dispatched")
        await repository.update_step_state(step.step_id, "unknown")

        await repository.record_step_receipt(step.step_id, receipt)
        pending = await repository.get_step(step.step_id)
        pending_facts = await repository.command_facts(command.command_id)

        await repository.settle_step(step.step_id, receipt)
        settled = await repository.get_step(step.step_id)
        settled_facts = await repository.command_facts(command.command_id)
    finally:
        await repository.close()

    assert pending is not None and pending.state == "unknown"
    assert pending.receipt == receipt
    assert pending_facts["receipts"] == 1
    assert settled is not None and settled.state == "settled"
    assert settled.receipt == receipt
    assert settled_facts["receipts"] == 1
    assert persisted_settled_at(tmp_path / "pending-receipt.db", step.step_id) == (
        1_800_000_000_123
    )


async def test_sqlite_concurrent_same_receipt_settlement_is_budget_idempotent(tmp_path) -> None:
    path = tmp_path / "concurrent-settlement.db"
    repository = SQLiteCommandJournal(path)
    await repository.connect()
    try:
        command, _ = await repository.create_command(draft("concurrent", "f" * 64))
        step = StepRecord(
            step_id="step-concurrent",
            command_id=command.command_id,
            ordinal=1,
            strategy_state_hash="a" * 64,
            capability="attack",
            params_hash="b" * 64,
            params={"target": "zombie"},
            correlation_id="correlation-concurrent",
            runtime_instance_id="runtime-concurrent",
            state="reserved",
            reservation={"max_actions": 1},
            before_observation_hash="c" * 64,
        )
        receipt = {
            "receipt_id": "receipt-concurrent",
            "content_hash": "d" * 64,
            "outcome": "success",
        }
        await repository.reserve_step(step)
        await repository.update_step_state(step.step_id, "dispatched")

        first = await repository.settle_step(
            step.step_id,
            receipt,
            settled_usage={"max_actions": 1},
            reserved_usage={},
        )
        replays = await asyncio.gather(
            repository.settle_step(
                step.step_id,
                receipt,
                settled_usage={"max_actions": 99},
                reserved_usage={"max_actions": 99},
            ),
            repository.settle_step(
                step.step_id,
                receipt,
                settled_usage={"max_actions": 99},
                reserved_usage={"max_actions": 99},
            ),
        )
        facts = await repository.command_facts(command.command_id)
    finally:
        await repository.close()

    assert first.state == "settled"
    assert all(item.state == "settled" for item in replays)
    assert facts["receipts"] == 1
    assert persisted_budget(path, command.command_id) == (2, {"max_actions": 1}, {})


async def test_sqlite_rejects_different_receipt_for_settled_step(tmp_path) -> None:
    path = tmp_path / "settlement-conflict.db"
    repository = SQLiteCommandJournal(path)
    await repository.connect()
    try:
        command, _ = await repository.create_command(draft("conflict", "e" * 64))
        step = StepRecord(
            step_id="step-conflict",
            command_id=command.command_id,
            ordinal=1,
            strategy_state_hash="a" * 64,
            capability="attack",
            params_hash="b" * 64,
            params={"target": "zombie"},
            correlation_id="correlation-conflict",
            runtime_instance_id="runtime-conflict",
            state="reserved",
            reservation={"max_actions": 1},
            before_observation_hash="c" * 64,
        )
        first_receipt = {
            "receipt_id": "receipt-first",
            "content_hash": "d" * 64,
            "outcome": "success",
        }
        different_receipt = {
            "receipt_id": "receipt-different",
            "content_hash": "f" * 64,
            "outcome": "success",
        }
        await repository.reserve_step(step)
        await repository.update_step_state(step.step_id, "dispatched")
        await repository.settle_step(
            step.step_id,
            first_receipt,
            settled_usage={"max_actions": 1},
            reserved_usage={},
        )

        with pytest.raises(ValueError, match="step settlement receipt conflict"):
            await repository.settle_step(
                step.step_id,
                different_receipt,
                settled_usage={"max_actions": 99},
                reserved_usage={"max_actions": 99},
            )
        persisted = await repository.get_step(step.step_id)
        facts = await repository.command_facts(command.command_id)
    finally:
        await repository.close()

    assert persisted is not None and persisted.receipt == first_receipt
    assert facts["receipts"] == 1
    assert persisted_budget(path, command.command_id) == (2, {"max_actions": 1}, {})


async def test_existing_blocked_unknown_keeps_restart_quarantined() -> None:
    repository = InMemoryCommandJournal()
    command, _ = await repository.create_command(draft("one", "a" * 64))
    running = await repository.transition(
        command.command_id,
        expected_version=0,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="worker",
        occurred_at_ms=110,
    )
    await repository.transition(
        running.command_id,
        expected_version=running.state_version,
        target=CommandState.BLOCKED_UNKNOWN,
        reason_code="UNKNOWN",
        actor="controller",
        occurred_at_ms=120,
    )

    recovery = await repository.recover_startup(occurred_at_ms=200)

    assert recovery.quarantined is True
    assert recovery.blocked_command_ids == (command.command_id,)


async def test_explicit_new_session_reopens_admission_without_losing_history(tmp_path) -> None:
    repository = SQLiteCommandJournal(tmp_path / "new-session.db")
    await repository.connect()
    try:
        first, _ = await repository.create_command(draft("first", "a" * 64))
        await repository.begin_shutdown(occurred_at_ms=200)
        with pytest.raises(RuntimeError, match="CONTROLLER_NOT_ACCEPTING_EXECUTE"):
            await repository.create_command(draft("blocked", "b" * 64))

        await repository.begin_session(occurred_at_ms=300)
        second, _ = await repository.create_command(draft("second", "c" * 64))
        projection = await repository.read_projection("principal:a")
    finally:
        await repository.close()

    assert first.command_id != second.command_id
    assert {item.command_id for item in projection.commands} == {
        first.command_id,
        second.command_id,
    }
