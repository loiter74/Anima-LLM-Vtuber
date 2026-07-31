from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from animetta.orchestration.chat_contracts import (
    ChatTransportMode,
    ChatTurnCommand,
)
from animetta.orchestration.server.handlers.chat_handlers import ChatHandlers


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
    admin._get_or_create_orchestrator = AsyncMock()
    return ChatHandlers(sio, MagicMock(), admin), sio, admin


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
