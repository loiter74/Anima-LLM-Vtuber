from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import pytest

from animetta.config import ReplyPolicyConfig
from animetta.services.bilibili.danmaku_buffer import DanmakuBuffer
from animetta.services.bilibili.gateway import DanmakuServiceGateway
from animetta.services.bilibili.livestream_session import LivestreamSession
from animetta.services.bilibili.livestream_state import LivestreamState
from animetta.services.bilibili.models import DanmakuMessage
from animetta.services.bilibili.reply_admission import ReplyAdmissionController


class FakeGateway:
    def __init__(self, room_id: int, sessdata: str = "") -> None:
        self.room_id = room_id
        self.sessdata = sessdata
        self.started = False
        self.stopped = False
        self.message_callback: Callable[[DanmakuMessage], None] | None = None
        self.status_callback: Callable[[bool, str], None] | None = None

    def set_message_callback(
        self,
        callback: Callable[[DanmakuMessage], None],
    ) -> None:
        self.message_callback = callback

    def set_status_callback(self, callback: Callable[[bool, str], None]) -> None:
        self.status_callback = callback

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def emit_status(self, connected: bool, message: str) -> None:
        assert self.status_callback is not None
        self.status_callback(connected, message)

    def emit_message(self, message: DanmakuMessage) -> None:
        assert self.message_callback is not None
        self.message_callback(message)


async def _settle_callbacks() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.fixture
def session_harness():
    gateways: list[FakeGateway] = []
    statuses: list[dict[str, object]] = []
    raw_messages: list[tuple[DanmakuMessage, int]] = []

    def factory(room_id: int, sessdata: str) -> FakeGateway:
        gateway = FakeGateway(room_id, sessdata)
        gateways.append(gateway)
        return gateway

    async def status_sink(payload: dict[str, object]) -> None:
        statuses.append(payload)

    async def raw_sink(message: DanmakuMessage, room_id: int) -> None:
        raw_messages.append((message, room_id))

    session = LivestreamSession(
        gateway_factory=factory,
        status_sink=status_sink,
        raw_message_sink=raw_sink,
    )
    return session, gateways, statuses, raw_messages


@pytest.mark.asyncio
async def test_initial_snapshot_is_stopped_and_public(session_harness) -> None:
    session, _, _, _ = session_harness

    snapshot = session.snapshot()

    assert snapshot == {
        "state": "stopped",
        "connected": False,
        "room_id": None,
        "desired_room_id": None,
        "retry_count": 0,
        "error_code": None,
        "generation_id": 0,
        "message": "Stopped",
        "updated_at": snapshot["updated_at"],
    }
    assert isinstance(snapshot["updated_at"], float)
    assert "sessdata" not in snapshot


@pytest.mark.asyncio
async def test_set_room_is_idempotent_and_waits_for_real_connected_status(
    session_harness,
) -> None:
    session, gateways, statuses, _ = session_harness

    first = await session.set_room(123, sessdata="secret")
    second = await session.set_room(123, sessdata="different-secret")

    assert len(gateways) == 1
    assert gateways[0].started is True
    assert gateways[0].sessdata == "secret"
    assert first["state"] == second["state"] == "connecting"
    assert first["connected"] is False
    assert first["room_id"] is None
    assert first["desired_room_id"] == 123
    assert first["generation_id"] == 1

    gateways[0].emit_status(True, "Connected")
    await _settle_callbacks()

    assert session.snapshot()["state"] == LivestreamState.LIVE.value
    assert session.snapshot()["connected"] is True
    assert session.snapshot()["room_id"] == 123
    assert statuses[-1]["state"] == "live"


@pytest.mark.asyncio
async def test_hot_switch_stops_old_gateway_and_ignores_stale_callbacks(
    session_harness,
) -> None:
    session, gateways, _, raw_messages = session_harness
    await session.set_room(100)
    old_gateway = gateways[0]
    old_gateway.emit_status(True, "Connected")
    await _settle_callbacks()

    switched = await session.set_room(200)

    assert old_gateway.stopped is True
    assert len(gateways) == 2
    assert gateways[1].started is True
    assert switched["state"] == "connecting"
    assert switched["connected"] is False
    assert switched["room_id"] is None
    assert switched["desired_room_id"] == 200
    assert switched["generation_id"] == 2

    old_gateway.emit_status(True, "Late connected")
    old_gateway.emit_message(DanmakuMessage(text="stale"))
    await _settle_callbacks()

    assert session.snapshot()["state"] == "connecting"
    assert raw_messages == []

    current_message = DanmakuMessage(text="current")
    gateways[1].emit_message(current_message)
    await _settle_callbacks()

    assert raw_messages == [(current_message, 200)]


@pytest.mark.asyncio
async def test_hot_switch_cancels_an_old_message_already_inside_raw_sink() -> None:
    gateways: list[FakeGateway] = []
    raw_started = asyncio.Event()
    release_raw = asyncio.Event()
    candidates: list[str] = []

    def factory(room_id: int, sessdata: str) -> FakeGateway:
        gateway = FakeGateway(room_id, sessdata)
        gateways.append(gateway)
        return gateway

    async def raw_sink(_message: DanmakuMessage, _room_id: int) -> None:
        raw_started.set()
        await release_raw.wait()

    async def candidate_sink(
        message: DanmakuMessage,
        _room_id: int,
        _generation_id: int,
    ) -> None:
        candidates.append(message.text)

    session = LivestreamSession(
        gateway_factory=factory,
        raw_message_sink=raw_sink,
        candidate_sink=candidate_sink,
    )
    await session.set_room(100)
    gateways[0].emit_message(DanmakuMessage(text="old"))
    await raw_started.wait()

    await session.set_room(200)
    release_raw.set()
    await _settle_callbacks()

    assert candidates == []
    assert session.callback_task_count == 0


@pytest.mark.asyncio
async def test_gateway_factory_failure_is_structured_and_redacts_exception() -> None:
    statuses: list[dict[str, object]] = []

    async def status_sink(payload: dict[str, object]) -> None:
        statuses.append(payload)

    def failing_factory(_room_id: int, _sessdata: str) -> FakeGateway:
        raise RuntimeError("sessdata=top-secret")

    session = LivestreamSession(
        gateway_factory=failing_factory,
        status_sink=status_sink,
    )

    snapshot = await session.set_room(777, sessdata="top-secret")

    assert snapshot["state"] == "error"
    assert snapshot["error_code"] == "gateway_start_failed"
    assert snapshot["message"] == "Bilibili gateway failed to start"
    assert "top-secret" not in repr(statuses)


@pytest.mark.asyncio
async def test_stop_timeout_does_not_block_session_shutdown() -> None:
    class SlowGateway(FakeGateway):
        def stop(self) -> None:
            time.sleep(0.2)
            super().stop()

    gateway = SlowGateway(456)

    async def status_sink(_payload: dict[str, object]) -> None:
        return None

    async def raw_sink(_message: DanmakuMessage, _room_id: int) -> None:
        return None

    session = LivestreamSession(
        gateway_factory=lambda _room_id, _sessdata: gateway,
        status_sink=status_sink,
        raw_message_sink=raw_sink,
        shutdown_timeout_seconds=0.01,
    )
    await session.set_room(456)

    started_at = time.monotonic()
    result = await session.stop()
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.15
    assert result["state"] == "stopped"
    assert result["connected"] is False
    assert result["desired_room_id"] is None
    assert result["error_code"] == "shutdown_timeout"

    reconnect = await session.set_room(789)
    assert reconnect["state"] == "error"
    assert reconnect["error_code"] == "shutdown_timeout"


@pytest.mark.asyncio
async def test_hot_switch_does_not_start_new_gateway_when_old_stop_times_out() -> None:
    class SlowGateway(FakeGateway):
        def stop(self) -> None:
            time.sleep(0.2)

    gateways: list[FakeGateway] = []

    def factory(room_id: int, sessdata: str) -> FakeGateway:
        gateway = SlowGateway(room_id, sessdata)
        gateways.append(gateway)
        return gateway

    session = LivestreamSession(
        gateway_factory=factory,
        shutdown_timeout_seconds=0.01,
    )
    await session.set_room(100)

    snapshot = await session.set_room(200)

    assert len(gateways) == 1
    assert snapshot["state"] == "error"
    assert snapshot["error_code"] == "shutdown_timeout"
    assert snapshot["desired_room_id"] == 200
    assert snapshot["message"] == "Previous gateway did not stop"

    retry = await session.set_room(300)
    assert len(gateways) == 1
    assert retry["error_code"] == "shutdown_timeout"


@pytest.mark.asyncio
async def test_retry_exhaustion_transitions_to_structured_error(
    session_harness,
) -> None:
    session, gateways, _, _ = session_harness
    await session.set_room(654)

    gateways[0].emit_status(False, "Max retries reached: unavailable")
    await _settle_callbacks()

    snapshot = session.snapshot()
    assert snapshot["state"] == "error"
    assert snapshot["connected"] is False
    assert snapshot["error_code"] == "retry_exhausted"
    assert snapshot["desired_room_id"] == 654


@pytest.mark.asyncio
async def test_missing_dependency_transitions_to_nonrecoverable_error(
    session_harness,
) -> None:
    session, gateways, _, _ = session_harness
    await session.set_room(655)

    gateways[0].emit_status(False, "Dependency unavailable")
    await _settle_callbacks()

    snapshot = session.snapshot()
    assert snapshot["state"] == "error"
    assert snapshot["error_code"] == "dependency_unavailable"
    assert snapshot["message"] == "Dependency unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "error_code"),
    [
        ("Invalid credentials", "invalid_credentials"),
        ("Invalid room", "invalid_room"),
    ],
)
async def test_terminal_gateway_status_has_stable_error_code(
    session_harness,
    message: str,
    error_code: str,
) -> None:
    session, gateways, _, _ = session_harness
    await session.set_room(656)

    gateways[0].emit_status(False, message)
    await _settle_callbacks()

    snapshot = session.snapshot()
    assert snapshot["state"] == "error"
    assert snapshot["error_code"] == error_code
    assert snapshot["message"] == message


def test_danmaku_service_gateway_adapts_existing_service_callbacks() -> None:
    class FakeService:
        def __init__(self, room_id: int, sessdata: str) -> None:
            self.room_id = room_id
            self.sessdata = sessdata
            self.on_message = None
            self.on_status = None
            self.started = False
            self.stopped = False

        def set_callback(self, callback) -> None:
            self.on_message = callback

        def set_status_callback(self, callback) -> None:
            self.on_status = callback

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    gateway = DanmakuServiceGateway(
        room_id=789,
        sessdata="cookie",
        service_factory=FakeService,
    )

    def message_callback(_message) -> None:
        return None

    def status_callback(_connected, _message) -> None:
        return None

    gateway.set_message_callback(message_callback)
    gateway.set_status_callback(status_callback)
    gateway.start()
    gateway.stop()

    assert gateway.room_id == 789
    assert gateway._service.sessdata == "cookie"
    assert gateway._service.on_message is message_callback
    assert gateway._service.on_status is status_callback
    assert gateway._service.started is True
    assert gateway._service.stopped is True


@pytest.mark.asyncio
async def test_raw_display_and_buffer_precede_and_survive_admission_rejection() -> None:
    gateway = FakeGateway(321)
    buffer = DanmakuBuffer()
    order: list[str] = []
    controller = ReplyAdmissionController(
        ReplyPolicyConfig(enabled=False),
        clock=lambda: 100.0,
    )

    async def raw_sink(_message: DanmakuMessage, _room_id: int) -> None:
        assert buffer.get_recent_danmaku() == ["不会触发 AI"]
        order.append("displayed")

    async def candidate_sink(
        message: DanmakuMessage,
        _room_id: int,
        _generation_id: int,
    ) -> None:
        assert order == ["displayed"]
        decision = controller.decide(message)
        assert decision.reason == "disabled"
        order.append("rejected")

    session = LivestreamSession(
        gateway_factory=lambda _room_id, _sessdata: gateway,
        raw_message_sink=raw_sink,
        candidate_sink=candidate_sink,
        buffer=buffer,
    )
    await session.set_room(321)

    gateway.emit_message(
        DanmakuMessage(text="不会触发 AI", timestamp=100.0),
    )
    await _settle_callbacks()

    assert order == ["displayed", "rejected"]
    assert buffer.get_recent_danmaku() == ["不会触发 AI"]
