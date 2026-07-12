from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.config import ReplyPolicyConfig
from animetta.orchestration.server.handlers.bilibili_handlers import BilibiliHandlers
from animetta.services.bilibili import DanmakuMessage


class FakeGateway:
    def __init__(self, room_id: int, _sessdata: str) -> None:
        self.room_id = room_id
        self.on_message = None
        self.on_status = None
        self.stopped = False

    def set_message_callback(self, callback) -> None:
        self.on_message = callback

    def set_status_callback(self, callback) -> None:
        self.on_status = callback

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True


async def settle_callbacks() -> None:
    for _ in range(4):
        await asyncio.sleep(0)


def _snapshot(state: str = "stopped") -> dict[str, object]:
    connected = state == "live"
    return {
        "state": state,
        "connected": connected,
        "room_id": 123 if connected else None,
        "desired_room_id": 123 if state != "stopped" else None,
        "retry_count": 0,
        "error_code": None,
        "generation_id": 1 if state != "stopped" else 0,
        "message": state.title(),
        "updated_at": 100.0,
    }


@pytest.fixture
def handler_harness():
    sio = MagicMock()
    sio.emit = AsyncMock()
    session = MagicMock()
    session.snapshot.return_value = _snapshot()
    session.set_room = AsyncMock(return_value=_snapshot("connecting"))
    session.stop = AsyncMock(return_value=_snapshot())
    handler = BilibiliHandlers(
        sio=sio,
        session_manager=MagicMock(),
        admin=MagicMock(),
        session=session,
        sessdata="server-secret",
    )
    return handler, sio, session


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, {}, {"room_id": 0}, {"room_id": "123"}])
async def test_connect_rejects_invalid_commands(handler_harness, data) -> None:
    handler, _, session = handler_harness

    ack = await handler.on_bilibili_connect("sid-1", data)

    assert ack == {
        "accepted": False,
        "state": "stopped",
        "error_code": "invalid_room_id",
        "message": "Invalid room ID",
    }
    session.set_room.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_acknowledges_acceptance_not_connection_truth(
    handler_harness,
) -> None:
    handler, sio, session = handler_harness

    ack = await handler.on_bilibili_connect("sid-1", {"room_id": 123})

    session.set_room.assert_awaited_once_with(123, sessdata="server-secret")
    assert ack == {
        "accepted": True,
        "state": "connecting",
        "error_code": None,
        "message": "Command accepted",
    }
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnect_accepts_missing_payload(handler_harness) -> None:
    handler, _, session = handler_harness

    ack = await handler.on_bilibili_disconnect("sid-1")

    session.stop.assert_awaited_once()
    assert ack["accepted"] is True
    assert ack["state"] == "stopped"


@pytest.mark.asyncio
async def test_update_room_uses_same_atomic_session_command(handler_harness) -> None:
    handler, _, session = handler_harness

    ack = await handler.on_bilibili_update_room("sid-1", {"room_id": 123})

    session.set_room.assert_awaited_once_with(123, sessdata="server-secret")
    assert ack["state"] == "connecting"


@pytest.mark.asyncio
async def test_new_client_receives_current_truthful_snapshot(handler_harness) -> None:
    handler, sio, session = handler_harness
    session.snapshot.return_value = _snapshot("reconnecting")

    await handler.emit_current_snapshot("sid-new")

    sio.emit.assert_awaited_once_with(
        "bilibili:danmaku_status",
        _snapshot("reconnecting"),
        to="sid-new",
    )


@pytest.mark.asyncio
async def test_session_status_sink_broadcasts_full_snapshot(handler_harness) -> None:
    handler, sio, _ = handler_harness
    payload = _snapshot("live")

    await handler.emit_status_snapshot(payload)

    sio.emit.assert_awaited_once_with("bilibili:danmaku_status", payload)


@pytest.mark.asyncio
async def test_real_session_integration_hot_switches_and_rejects_stale_raw() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    gateways: list[FakeGateway] = []

    def factory(room_id: int, sessdata: str) -> FakeGateway:
        gateway = FakeGateway(room_id, sessdata)
        gateways.append(gateway)
        return gateway

    handler = BilibiliHandlers(
        sio,
        MagicMock(),
        MagicMock(),
        gateway_factory=factory,
    )
    handler.configure({"reply_policy": {"enabled": False}})

    first_ack = await handler.on_bilibili_connect("sid", {"room_id": 100})
    stale_gateway = gateways[0]
    assert first_ack["state"] == "connecting"
    stale_gateway.on_message(DanmakuMessage(text="first"))
    await settle_callbacks()

    switch_ack = await handler.on_bilibili_update_room("sid", {"room_id": 200})
    stale_gateway.on_message(DanmakuMessage(text="stale"))
    gateways[1].on_message(DanmakuMessage(text="current"))
    await settle_callbacks()

    raw_texts = [
        call.args[1]["text"]
        for call in sio.emit.await_args_list
        if call.args[0] == "bilibili:danmaku"
    ]
    assert switch_ack["state"] == "connecting"
    assert stale_gateway.stopped is True
    assert raw_texts == ["first", "current"]


@pytest.mark.asyncio
async def test_real_session_integration_serializes_admitted_ai_reply() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    gateway = FakeGateway(300, "")
    handler = BilibiliHandlers(
        sio,
        MagicMock(),
        MagicMock(),
        reply_policy=ReplyPolicyConfig(
            ordinary_sample_rate=1.0,
            per_user_cooldown_seconds=0,
            duplicate_window_seconds=0,
        ),
        gateway_factory=lambda _room_id, _sessdata: gateway,
    )
    handler._process_ai_reply = AsyncMock()
    await handler.on_bilibili_connect("sid", {"room_id": 300})
    message = DanmakuMessage(text="普通弹幕", timestamp=time.time())

    gateway.on_message(message)
    for _ in range(20):
        await settle_callbacks()
        if handler._process_ai_reply.await_count:
            break

    handler._process_ai_reply.assert_awaited_once_with(message, 300)
    assert handler.metrics.displayed == 1
    assert handler.metrics.admitted == 1
    await handler.stop_bilibili()
