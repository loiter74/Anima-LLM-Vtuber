from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from animetta.orchestration.chat_contracts import ChatIdentity, ChatTransportMode
from animetta.orchestration.chat_delivery import ChatDelivery


def _identity() -> ChatIdentity:
    task_id = str(uuid4())
    return ChatIdentity(
        message_id=str(uuid4()),
        conversation_id=str(uuid4()),
        task_id=task_id,
        turn_id=task_id,
    )


@pytest.mark.asyncio
async def test_canonical_delivery_attaches_identity_and_emits_once() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    identity = _identity()
    delivery = ChatDelivery(sio, identity, ChatTransportMode.CANONICAL)

    await delivery.emit("chat", "sentence", {"text": "hello", "seq": 0, "lang": "zh"}, to="sid")

    sio.emit.assert_awaited_once()
    event, payload = sio.emit.await_args.args[:2]
    assert event == "chat:sentence"
    assert payload == {
        "text": "hello",
        "seq": 0,
        "lang": "zh",
        **identity.model_dump(),
    }


@pytest.mark.asyncio
async def test_legacy_delivery_selects_declared_alias_without_dual_emit() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    delivery = ChatDelivery(sio, _identity(), ChatTransportMode.LEGACY)

    await delivery.emit("chat", "expression", {"emotion": "happy"}, to="sid")

    sio.emit.assert_awaited_once()
    assert sio.emit.await_args.args[0] == "expression"


@pytest.mark.asyncio
async def test_delivery_rejects_identity_override() -> None:
    delivery = ChatDelivery(MagicMock(), _identity(), ChatTransportMode.CANONICAL)

    with pytest.raises(ValueError, match="identity"):
        await delivery.emit(
            "chat",
            "control",
            {"signal": "conversation-start", "task_id": str(uuid4())},
            to="sid",
        )


@pytest.mark.asyncio
async def test_delivery_rejects_missing_required_payload_field() -> None:
    delivery = ChatDelivery(MagicMock(), _identity(), ChatTransportMode.CANONICAL)

    with pytest.raises(ValueError, match="missing required"):
        await delivery.emit("chat", "sentence", {"text": "hello"}, to="sid")
