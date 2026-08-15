from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.orchestration.server.routes import register_routes
from animetta.services.command_inbox import CommandInbox, CommandKey, CommandStatus


async def _waiting_task(
    inbox: CommandInbox,
    *,
    task_id: str,
    retention: str = "temporary",
    expires_at: int | None = None,
) -> None:
    key = CommandKey("conversation:one", "chat.public", task_id)
    await inbox.accept(key, {"text": "connect"})
    await inbox.mark_processing(key)
    await inbox.wait_for_approval(
        key,
        {
            "approval_id": f"approval-{task_id}",
            "thread_id": f"turn:{task_id}",
            "owner_kind": "turn",
            "owner_id": task_id,
            "retention": retention,
            "expires_at": expires_at or int(time.time()) + 120,
            "tools": [{"name": "mc_connection", "arguments": {"operation": "connect"}}],
        },
    )


@pytest.mark.asyncio
async def test_reconnect_replays_pending_approval_snapshot(mock_socketio) -> None:
    inbox = CommandInbox(":memory:")
    await _waiting_task(inbox, task_id="reconnect")
    session_manager = MagicMock()
    handlers = register_routes(mock_socketio, session_manager, command_inbox=inbox)
    handlers.on_connect = AsyncMock()
    registered = {call.args[0]: call.args[1] for call in mock_socketio.on.call_args_list}

    await registered["connect"]("sid", {"REMOTE_ADDR": "127.0.0.1"}, None)

    handlers.on_connect.assert_awaited_once()
    emitted = [
        call
        for call in mock_socketio.emit.await_args_list
        if call.args and call.args[0] == "tool:approval_required"
    ]
    assert emitted[0].args[1]["approval_id"] == "approval-reconnect"
    await inbox.close()


@pytest.mark.asyncio
async def test_timeout_resumes_each_interrupt_as_rejected(mock_socketio) -> None:
    inbox = CommandInbox(":memory:")
    await _waiting_task(
        inbox,
        task_id="expired-temp",
        expires_at=int(time.time()) - 1,
    )
    await _waiting_task(
        inbox,
        task_id="expired-stable",
        retention="stable",
        expires_at=int(time.time()) - 1,
    )
    session_manager = MagicMock()
    handlers = register_routes(mock_socketio, session_manager, command_inbox=inbox)
    orchestrator = MagicMock()
    orchestrator.resume_checkpoint = AsyncMock(return_value={"response_text": "rejected"})
    handlers.base.get_or_create_orchestrator = AsyncMock(return_value=orchestrator)

    assert await handlers.expire_tool_approvals() == 2

    assert orchestrator.resume_checkpoint.await_count == 2
    assert all(
        call.kwargs["approved"] is False for call in orchestrator.resume_checkpoint.await_args_list
    )
    for task_id in ("expired-temp", "expired-stable"):
        task = await inbox.get(CommandKey("conversation:one", "chat.public", task_id))
        assert task.task is not None
        assert task.task.status is CommandStatus.CANCELLED
    await inbox.close()
