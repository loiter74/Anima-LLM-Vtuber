from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from animetta.orchestration.chat_contracts import ChatIdentity, ChatTransportMode
from animetta.orchestration.chat_delivery import ChatDelivery, resolve_delivery_target


def _identity() -> ChatIdentity:
    task_id = str(uuid4())
    return ChatIdentity(
        message_id=str(uuid4()),
        conversation_id=str(uuid4()),
        task_id=task_id,
        turn_id=task_id,
    )


def test_only_trusted_developer_livestream_reply_broadcasts() -> None:
    trusted = {
        "session_id": "sid",
        "channel_id": "sid",
        "metadata": {
            "source": "developer_console",
            "actor_role": "developer",
            "audience": "livestream",
        },
    }
    forged_ordinary = {
        **trusted,
        "metadata": {"actor_role": "developer", "audience": "livestream"},
    }

    assert resolve_delivery_target(trusted) is None
    assert resolve_delivery_target(forged_ordinary) == "sid"


def test_server_admitted_bilibili_reply_broadcasts_to_the_live_page() -> None:
    state = {
        "session_id": "bilibili-session",
        "channel_id": "bilibili",
        "metadata": {
            "source": "bilibili:danmaku",
            "actor_role": "viewer",
            "audience": "livestream",
        },
    }

    assert resolve_delivery_target(state) is None


def test_only_trusted_proactive_host_turn_broadcasts_to_the_live_page() -> None:
    trusted = {
        "session_id": "bilibili-session",
        "channel_id": "bilibili",
        "metadata": {
            "source": "bilibili:proactive_topic",
            "actor_role": "host",
            "audience": "livestream",
        },
    }

    assert resolve_delivery_target(trusted) is None
    assert (
        resolve_delivery_target(
            {**trusted, "metadata": {**trusted["metadata"], "actor_role": "viewer"}}
        )
        == "bilibili"
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


@pytest.mark.asyncio
async def test_stream_delivery_contracts_are_correlated_and_ordered() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    delivery = ChatDelivery(sio, _identity(), ChatTransportMode.CANONICAL)
    stream_id = str(uuid4())

    await delivery.emit(
        "chat",
        "audio_stream_start",
        {
            "stream_id": stream_id,
            "format": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
            "emotion": "thinking",
        },
        to="sid",
    )
    await delivery.emit(
        "chat",
        "audio_stream_chunk",
        {"stream_id": stream_id, "sequence": 0, "audio_data": "AAE="},
        to="sid",
    )
    await delivery.emit(
        "chat",
        "audio_stream_end",
        {"stream_id": stream_id, "final_sequence": 0, "status": "completed"},
        to="sid",
    )

    assert [call.args[0] for call in sio.emit.await_args_list] == [
        "chat:audio_stream_start",
        "chat:audio_stream_chunk",
        "chat:audio_stream_end",
    ]
