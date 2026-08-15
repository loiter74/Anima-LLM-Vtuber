from __future__ import annotations

import asyncio

from animetta.services.command_inbox import (
    CommandDecision,
    CommandInbox,
    CommandInboxError,
    CommandKey,
    CommandStatus,
    TaskResultTooLargeError,
)


async def test_concurrent_duplicate_accepts_execute_once(tmp_path) -> None:
    inbox = CommandInbox(tmp_path / "commands.db")
    await inbox.start()
    key = CommandKey("dashboard", "singing.process", "task-1")

    results = await asyncio.gather(*(inbox.accept(key, {"url": "BV1"}) for _ in range(50)))

    assert sum(result.decision is CommandDecision.EXECUTE for result in results) == 1
    assert sum(result.decision is CommandDecision.OBSERVE for result in results) == 49
    await inbox.close()


async def test_same_identity_with_different_request_conflicts(tmp_path) -> None:
    inbox = CommandInbox(tmp_path / "commands.db")
    key = CommandKey("dashboard", "meme.collect", "task-1")

    assert (await inbox.accept(key, {"source": "bilibili"})).decision is CommandDecision.EXECUTE
    result = await inbox.accept(key, {"source": "manual"})

    assert result.decision is CommandDecision.CONFLICT
    await inbox.close()


async def test_completed_result_replays_across_reopen(tmp_path) -> None:
    path = tmp_path / "commands.db"
    key = CommandKey("sandbox:conversation", "chat.sandbox", "task-1")
    inbox = CommandInbox(path)
    await inbox.accept(key, {"text": "hello"})
    await inbox.mark_processing(key)
    await inbox.succeed(key, {"text": "world", "chunks": ["world"]})
    await inbox.close()

    reopened = CommandInbox(path)
    assert await reopened.start() == 0
    result = await reopened.get(key)

    assert result.decision is CommandDecision.REPLAY
    assert result.task is not None
    assert result.task.result == {"chunks": ["world"], "text": "world"}
    await reopened.close()


async def test_start_interrupts_unknown_active_work(tmp_path) -> None:
    path = tmp_path / "commands.db"
    key = CommandKey("dashboard", "memory.organize", "task-1")
    inbox = CommandInbox(path)
    await inbox.accept(key, {})
    await inbox.mark_processing(key)
    await inbox.close()

    reopened = CommandInbox(path)
    assert await reopened.start() == 1
    result = await reopened.get(key)

    assert result.decision is CommandDecision.TERMINAL
    assert result.task is not None
    assert result.task.status is CommandStatus.INTERRUPTED
    assert result.task.error_code == "SERVER_RESTARTED"
    await reopened.close()


async def test_waiting_approval_survives_reopen_for_reconciliation(tmp_path) -> None:
    path = tmp_path / "commands.db"
    key = CommandKey("conversation:one", "chat.public", "task-approval")
    inbox = CommandInbox(path)
    await inbox.accept(key, {"text": "connect"})
    await inbox.mark_processing(key)
    await inbox.wait_for_approval(
        key,
        {
            "approval_id": "approval-1",
            "thread_id": "turn:task-approval",
            "owner_kind": "turn",
            "owner_id": "task-approval",
            "retention": "temporary",
            "expires_at": 4_000_000_000,
        },
    )
    await inbox.close()

    reopened = CommandInbox(path)
    assert await reopened.start() == 0

    waiting = await reopened.waiting_approvals()
    assert len(waiting) == 1
    assert waiting[0].status is CommandStatus.WAITING_APPROVAL
    assert waiting[0].progress is not None
    assert waiting[0].progress["thread_id"] == "turn:task-approval"
    await reopened.close()


async def test_restart_reconciliation_fails_approval_without_checkpoint(tmp_path) -> None:
    inbox = CommandInbox(tmp_path / "commands.db")
    key = CommandKey("dashboard", "chat.text", "task-missing")
    await inbox.accept(key, {"text": "connect"})
    await inbox.mark_processing(key)
    await inbox.wait_for_approval(
        key,
        {"approval_id": "approval-1", "thread_id": "turn:task-missing"},
    )

    async def checkpoint_exists(_thread_id: str) -> bool:
        return False

    reconciled = await inbox.reconcile_waiting_approvals(checkpoint_exists)

    result = await inbox.get(key)
    assert reconciled == 1
    assert result.task is not None
    assert result.task.status is CommandStatus.FAILED
    assert result.task.error_code == "CHECKPOINT_UNAVAILABLE"
    await inbox.close()


async def test_concurrent_approval_resume_is_claimed_once(tmp_path) -> None:
    inbox = CommandInbox(tmp_path / "commands.db")
    key = CommandKey("dashboard", "chat.text", "task-approval")
    await inbox.accept(key, {"text": "connect"})
    await inbox.mark_processing(key)
    await inbox.wait_for_approval(key, {"approval_id": "approval-1"})

    results = await asyncio.gather(
        inbox.resume_after_approval(key),
        inbox.resume_after_approval(key),
        return_exceptions=True,
    )

    assert sum(isinstance(result, CommandInboxError) for result in results) == 1
    assert (
        sum(
            not isinstance(result, BaseException) and result.status is CommandStatus.PROCESSING
            for result in results
        )
        == 1
    )
    await inbox.close()


async def test_terminal_transition_is_not_reopened(tmp_path) -> None:
    inbox = CommandInbox(tmp_path / "commands.db")
    key = CommandKey("dashboard", "singing.process", "task-1")
    await inbox.accept(key, {"url": "BV1"})
    await inbox.mark_processing(key)
    first = await inbox.succeed(key, {"audio_url": "/one.wav"})

    second = await inbox.fail(key, error_code="LATE_FAILURE", error_message="too late")

    assert first.status is CommandStatus.SUCCEEDED
    assert second.status is CommandStatus.SUCCEEDED
    assert second.result == {"audio_url": "/one.wav"}
    await inbox.close()


async def test_oversize_result_fails_with_explicit_error_code(tmp_path) -> None:
    inbox = CommandInbox(tmp_path / "commands.db", result_limit_bytes=1024)
    key = CommandKey("dashboard", "singing.process", "task-1")
    await inbox.accept(key, {"url": "BV1"})
    await inbox.mark_processing(key)

    try:
        await inbox.succeed(key, {"payload": "x" * 2048})
    except TaskResultTooLargeError:
        pass
    else:
        raise AssertionError("oversize result must be rejected")

    current = await inbox.get(key)
    assert current.task is not None
    assert current.task.status is CommandStatus.FAILED
    assert current.task.error_code == "TASK_RESULT_TOO_LARGE"
    await inbox.close()


async def test_expired_cleanup_is_bounded_and_keeps_active_tasks(tmp_path) -> None:
    inbox = CommandInbox(tmp_path / "commands.db", retention_seconds=1)
    active = CommandKey("dashboard", "memory.organize", "active")
    await inbox.accept(active, {"operation": "organize"})
    for index in range(3):
        key = CommandKey("dashboard", "meme.collect", f"done-{index}")
        await inbox.accept(key, {"source": "bilibili"})
        await inbox.succeed(key, {"index": index})

    assert inbox._db is not None
    await inbox._db.execute("UPDATE command_tasks SET expires_at_ms=0 WHERE status='succeeded'")
    await inbox._db.commit()

    assert await inbox.cleanup_expired(limit=2) == 2
    assert (await inbox.get(active)).decision is CommandDecision.OBSERVE
    assert await inbox.cleanup_expired(limit=2) == 1
    await inbox.close()
