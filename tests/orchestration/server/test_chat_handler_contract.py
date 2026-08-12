from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from animetta.orchestration.chat_contracts import (
    ChatTransportMode,
    ChatTurnCommand,
)
from animetta.orchestration.server.handlers.chat_handlers import ChatHandlers
from animetta.services.llm.interface import LLMInterface


def _command(
    *,
    conversation_id: str | None = None,
    text: str = "hello",
    source: str = "text",
    is_acceptance: bool = False,
) -> ChatTurnCommand:
    task_id = str(uuid4())
    return ChatTurnCommand(
        text=text,
        message_id=str(uuid4()),
        conversation_id=conversation_id or str(uuid4()),
        task_id=task_id,
        turn_id=task_id,
        transport_mode=ChatTransportMode.CANONICAL,
        source=source,
        is_acceptance=is_acceptance,
    )


@pytest.mark.asyncio
async def test_livestream_acceptance_uses_bilibili_personality_channel(handler) -> None:
    chat, _, admin = handler
    command = _command(source="livestream", is_acceptance=True)
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(return_value={})
    admin._get_or_create_orchestrator.return_value = orchestrator

    await chat.on_text_command("sid", command)

    kwargs = orchestrator.process_text.await_args.kwargs
    assert kwargs["channel_id"] == "sid"
    assert kwargs["channel"] == "bilibili"
    assert kwargs["user_id"] == "bilibili:user"


@pytest.fixture
def handler():
    sio = MagicMock()
    sio.emit = AsyncMock()
    admin = MagicMock()
    admin.live_session_id = "live-session-1"
    admin._get_or_create_orchestrator = AsyncMock()
    return ChatHandlers(sio, MagicMock(), admin), sio, admin


@pytest.mark.asyncio
async def test_developer_event_injects_trusted_live_metadata_without_emitting_input(
    handler,
) -> None:
    chat, sio, admin = handler
    command = _command(text="去 Minecraft 看看基地")
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(return_value={})
    admin._get_or_create_orchestrator.return_value = orchestrator

    await chat.on_text_command("sid", command, developer_console=True)

    kwargs = orchestrator.process_text.await_args.kwargs
    assert kwargs["text"] == command.text
    assert kwargs["user_id"] == "developer_console:developer"
    assert kwargs["actor_role"] == "developer"
    assert kwargs["source"] == "developer_console"
    assert kwargs["live_session_id"] == "live-session-1"
    assert kwargs["audience"] == "livestream"
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_probe_is_filtered_before_command_normalization(handler) -> None:
    chat, sio, admin = handler

    await chat.on_text_event("sid", "chat:text", {"text": "ping"})

    admin._get_or_create_orchestrator.assert_not_awaited()
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_command_identity_is_propagated_to_orchestrator(handler) -> None:
    chat, _, admin = handler
    command = _command()
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(return_value={})
    admin._get_or_create_orchestrator.return_value = orchestrator

    await chat.on_text_command("sid", command)

    orchestrator.process_text.assert_awaited_once_with(
        text=command.text,
        user_id="local:owner",
        user_name="User",
        channel_id="sid",
        message_id=command.message_id,
        conversation_id=command.conversation_id,
        task_id=command.task_id,
        turn_id=command.task_id,
        transport_mode=command.transport_mode.value,
        channel="local",
    )


@pytest.mark.asyncio
async def test_same_conversation_turns_are_serialized(handler) -> None:
    chat, _, admin = handler
    conversation_id = str(uuid4())
    active = 0
    peak = 0
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def process_text(**_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if not first_entered.is_set():
            first_entered.set()
            await release_first.wait()
        active -= 1
        return {}

    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(side_effect=process_text)
    admin._get_or_create_orchestrator.return_value = orchestrator
    first = asyncio.create_task(
        chat.on_text_command("sid", _command(conversation_id=conversation_id, text="one"))
    )
    await first_entered.wait()
    second = asyncio.create_task(
        chat.on_text_command("sid", _command(conversation_id=conversation_id, text="two"))
    )
    await asyncio.sleep(0)

    assert orchestrator.process_text.await_count == 1
    release_first.set()
    await asyncio.gather(first, second)
    assert peak == 1


@pytest.mark.asyncio
async def test_processing_error_emits_correlated_typed_error(handler) -> None:
    chat, sio, admin = handler
    command = _command()
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(return_value={"error": "provider unavailable"})
    admin._get_or_create_orchestrator.return_value = orchestrator

    await chat.on_text_command("sid", command)

    event, payload = sio.emit.await_args.args[:2]
    assert event == "system:error"
    assert payload["type"] == "processing_error"
    assert payload["component"] == "workflow"
    assert payload["message_id"] == command.message_id
    assert payload["conversation_id"] == command.conversation_id
    assert payload["task_id"] == command.task_id
    assert payload["turn_id"] == command.task_id


@pytest.mark.asyncio
async def test_invalid_canonical_command_emits_generated_correlated_error(handler) -> None:
    chat, sio, admin = handler

    await chat.on_text_event("sid", "chat:text", {"text": "hello"})

    admin._get_or_create_orchestrator.assert_not_awaited()
    event, payload = sio.emit.await_args.args[:2]
    assert event == "system:error"
    assert payload["type"] == "validation_error"
    assert payload["turn_id"] == payload["task_id"]
    for field in ("message_id", "conversation_id", "task_id"):
        assert str(uuid4().__class__(payload[field])) == payload[field]


async def test_sandbox_uses_private_service_context_and_emits_only_sandbox_chunks(
    handler,
) -> None:
    chat, sio, admin = handler
    config = MagicMock()
    config.providers = {"llm": MagicMock(type="deepseek", model="deepseek-v4-flash")}
    config.get_system_prompt.return_value = "persona"
    admin.get_active_config.return_value = config

    class SandboxLLM(LLMInterface):
        async def chat(self, user_input: str, **kwargs) -> str:  # pragma: no cover
            raise AssertionError

        async def chat_messages(self, messages: list[dict], **kwargs) -> str:
            return "unused"

        async def chat_messages_stream(self, messages, **kwargs):
            yield "私密"
            yield "回复"

        def chat_stream(self, user_input: str, **kwargs):  # pragma: no cover
            raise AssertionError

        def set_system_prompt(self, prompt: str) -> None: ...

        def get_history(self) -> list[dict]:
            return []

        def clear_history(self) -> None: ...

        async def close(self) -> None: ...

        def handle_interrupt(self, heard_response: str = "") -> None: ...

        def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None: ...

    context = MagicMock(llm_engine=SandboxLLM())
    admin.get_or_create_context = AsyncMock(return_value=context)
    task_id = str(uuid4())
    payload = {
        "text": "测试私密回复",
        "history": [],
        "message_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "task_id": task_id,
        "turn_id": task_id,
    }

    with patch(
        "animetta.orchestration.server.handlers.chat_handlers.resolve_service_identity",
        return_value={
            "type": "deepseek",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "voice": None,
        },
    ):
        await chat.on_sandbox_request("sid", payload)
        await chat._sandbox_tasks[task_id]

    admin._get_or_create_orchestrator.assert_not_awaited()
    assert [call.args[0] for call in sio.emit.await_args_list] == [
        "chat:sandbox_chunk",
        "chat:sandbox_chunk",
        "chat:sandbox_chunk",
    ]
    assert all(call.kwargs["to"] == "sid" for call in sio.emit.await_args_list)
    final = sio.emit.await_args_list[-1].args[1]
    assert final["provider"] == "deepseek"
    assert final["model"] == "deepseek-v4-flash"
    assert final["is_complete"] is True


async def test_sandbox_rejects_mismatched_turn_identity(handler) -> None:
    chat, sio, admin = handler
    payload = {
        "text": "invalid identity",
        "history": [],
        "message_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "task_id": str(uuid4()),
        "turn_id": str(uuid4()),
    }

    await chat.on_sandbox_request("sid", payload)

    admin.get_or_create_context.assert_not_called()
    event, response = sio.emit.await_args.args[:2]
    assert event == "chat:sandbox_chunk"
    assert response["error_code"] == "validation_error"


async def test_sandbox_cancel_is_scoped_to_owning_socket(handler) -> None:
    chat, _, _ = handler

    async def wait_forever() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(wait_forever())
    task_id = str(uuid4())
    identity = {
        "message_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "task_id": task_id,
        "turn_id": task_id,
    }
    chat._sandbox_tasks[task_id] = task
    chat._sandbox_task_sids[task_id] = "owner"

    await chat.on_sandbox_cancel("other", identity)
    assert not task.cancelled()

    await chat.on_sandbox_cancel("owner", identity)
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_sandbox_rejects_duplicate_task_identity(handler) -> None:
    chat, sio, _ = handler

    async def wait_forever() -> None:
        await asyncio.Event().wait()

    existing = asyncio.create_task(wait_forever())
    task_id = str(uuid4())
    payload = {
        "text": "duplicate",
        "history": [],
        "message_id": str(uuid4()),
        "conversation_id": str(uuid4()),
        "task_id": task_id,
        "turn_id": task_id,
    }
    chat._sandbox_tasks[task_id] = existing
    chat._sandbox_task_sids[task_id] = "owner"

    await chat.on_sandbox_request("owner", payload)

    assert chat._sandbox_tasks[task_id] is existing
    assert not existing.cancelled()
    response = sio.emit.await_args.args[1]
    assert response["error_code"] == "task_conflict"
    existing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await existing


@pytest.mark.asyncio
async def test_completed_public_turn_replays_text_without_running_orchestrator_twice(
    handler,
) -> None:
    chat, sio, admin = handler
    command = _command()
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(
        return_value={"response_text": "只重放文字", "response_chunks": ["只重放", "文字"]}
    )
    admin._get_or_create_orchestrator.return_value = orchestrator

    await chat.on_text_command("sid", command)
    sio.emit.reset_mock()
    await chat.on_text_command("retry-sid", command)

    orchestrator.process_text.assert_awaited_once()
    assert [call.args[0] for call in sio.emit.await_args_list] == [
        "chat:sentence",
        "chat:sentence",
        "chat:sentence",
        "chat:control",
    ]
    assert all(call.kwargs["to"] == "retry-sid" for call in sio.emit.await_args_list)
