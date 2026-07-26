from __future__ import annotations

import asyncio
import base64
import importlib
import json
from collections import deque
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any

import pytest

from animetta.core.readiness import unwrap_tracing_proxy
from animetta.services.tts.factory import TTSFactory


class FakeWebSocket:
    def __init__(
        self,
        incoming: list[dict[str, Any] | BaseException],
        *,
        receive_delay: float = 0.0,
    ) -> None:
        self.incoming = deque(
            event if isinstance(event, BaseException) else json.dumps(event) for event in incoming
        )
        self.receive_delay = receive_delay
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str | bytes) -> None:
        assert isinstance(message, str)
        self.sent.append(json.loads(message))

    async def recv(self) -> str | bytes:
        if self.receive_delay:
            await asyncio.sleep(self.receive_delay)
        if not self.incoming:
            raise AssertionError("fake WebSocket has no remaining events")
        event = self.incoming.popleft()
        if isinstance(event, BaseException):
            raise event
        return event


class FakeConnection(AbstractAsyncContextManager[FakeWebSocket]):
    def __init__(self, socket: FakeWebSocket) -> None:
        self.socket = socket
        self.closed = False

    async def __aenter__(self) -> FakeWebSocket:
        return self.socket

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.closed = True
        return None


class FakeConnector:
    def __init__(self, sockets: list[FakeWebSocket]) -> None:
        self.sockets = deque(sockets)
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.connections: list[FakeConnection] = []

    def __call__(
        self, url: str, headers: Mapping[str, str]
    ) -> AbstractAsyncContextManager[FakeWebSocket]:
        self.calls.append((url, dict(headers)))
        connection = FakeConnection(self.sockets.popleft())
        self.connections.append(connection)
        return connection


def response_events(*chunks: bytes, include_session_finished: bool = False) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {"type": "input_text_buffer.committed"},
        {"type": "response.created", "response": {"id": "response"}},
    ]
    events.extend(
        {"type": "response.audio.delta", "delta": base64.b64encode(chunk).decode("ascii")}
        for chunk in chunks
    )
    events.extend(
        [
            {"type": "response.audio.done"},
            {"type": "response.done", "response": {"id": "response", "status": "completed"}},
        ]
    )
    if include_session_finished:
        events.append({"type": "session.finished"})
    return events


def socket_events(*responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"type": "session.created", "session": {"id": "session"}},
        {"type": "session.updated", "session": {"id": "session"}},
        *(event for response in responses for event in response),
    ]


async def collect(chunks: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in chunks]


async def test_same_instruction_reuses_one_hot_connection_for_ordered_pcm() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    socket = FakeWebSocket(
        socket_events(
            response_events(b"first-0", b"first-1"),
            response_events(b"second-0", include_session_finished=True),
        )
    )
    connector = FakeConnector([socket])
    service = module.DashScopeRealtimeTTS(
        api_key="secret",
        connector=connector,
    )

    first = await collect(service.synthesize_stream("第一句", instruction="same"))
    second = await collect(service.synthesize_stream("第二句", instruction="same"))
    await service.close()

    assert first == [b"first-0", b"first-1"]
    assert second == [b"second-0"]
    assert len(connector.calls) == 1
    assert connector.calls[0][0].endswith("?model=qwen3-tts-instruct-flash-realtime")
    assert connector.calls[0][1]["Authorization"] == "Bearer secret"
    assert [event["type"] for event in socket.sent] == [
        "session.update",
        "input_text_buffer.append",
        "input_text_buffer.commit",
        "input_text_buffer.append",
        "input_text_buffer.commit",
        "session.finish",
    ]
    assert socket.sent[0]["session"]["voice"] == "Seren"
    assert socket.sent[0]["session"]["instructions"] == "same"
    assert connector.connections[0].closed is True


async def test_cancelling_lock_waiter_does_not_close_active_hot_connection() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")

    class CoordinatedWebSocket(FakeWebSocket):
        def __init__(self) -> None:
            super().__init__(
                socket_events(response_events(b"owner", include_session_finished=True))
            )
            self.response_gate = asyncio.Event()
            self.owner_committed = asyncio.Event()
            self.recv_calls = 0

        async def send(self, message: str | bytes) -> None:
            await super().send(message)
            if self.sent[-1]["type"] == "input_text_buffer.commit":
                self.owner_committed.set()

        async def recv(self) -> str | bytes:
            self.recv_calls += 1
            if self.recv_calls > 2:
                await self.response_gate.wait()
            return await super().recv()

    socket = CoordinatedWebSocket()
    connector = FakeConnector([socket])
    service = module.DashScopeRealtimeTTS(api_key="secret", connector=connector)
    owner = asyncio.create_task(collect(service.synthesize_stream("第一句", instruction="same")))
    await asyncio.wait_for(socket.owner_committed.wait(), timeout=1.0)
    waiter = asyncio.create_task(collect(service.synthesize_stream("第二句", instruction="same")))
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    closed_while_owner_active = connector.connections[0].closed

    socket.response_gate.set()
    assert await asyncio.wait_for(owner, timeout=1.0) == [b"owner"]
    await service.close()

    assert closed_while_owner_active is False


async def test_cancelled_owner_bounds_a_slow_connector_close() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")

    class SlowCloseConnection(FakeConnection):
        def __init__(self, socket: FakeWebSocket) -> None:
            super().__init__(socket)
            self.close_started = asyncio.Event()

        async def __aexit__(self, exc_type, exc_value, traceback) -> bool | None:
            self.close_started.set()
            await asyncio.Future()

    socket = FakeWebSocket(socket_events(response_events(b"first")))
    connection = SlowCloseConnection(socket)

    def connector(url: str, headers: Mapping[str, str]):
        del url, headers
        return connection

    service = module.DashScopeRealtimeTTS(api_key="secret", connector=connector)
    service._session_close_timeout_seconds = 0.02
    stream = service.synthesize_stream("第一句", instruction="same")
    assert await anext(stream) == b"first"

    started = asyncio.get_running_loop().time()
    await asyncio.wait_for(stream.aclose(), timeout=0.2)
    elapsed = asyncio.get_running_loop().time() - started

    assert connection.close_started.is_set()
    assert elapsed < 0.2


async def test_preload_opens_all_six_emotion_hot_connections() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    instructions = importlib.import_module("animetta.services.tts.emotion_instructions")
    sockets = [
        FakeWebSocket(socket_events(response_events(b"warm", include_session_finished=True))),
        *[FakeWebSocket(socket_events([{"type": "session.finished"}])) for _ in range(5)],
    ]
    connector = FakeConnector(sockets)
    service = module.DashScopeRealtimeTTS(api_key="secret", connector=connector)

    await service.preload()
    chunks = await collect(
        service.synthesize_stream(
            "默认情绪",
            instruction=instructions.build_emotion_instruction("neutral"),
        )
    )
    await service.close()

    assert chunks == [b"warm"]
    assert len(connector.calls) == 6
    assert [socket.sent[0]["session"]["instructions"] for socket in sockets] == list(
        instructions.all_emotion_instructions()
    )


async def test_preload_retries_one_transient_connection_failure(monkeypatch) -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    failed = FakeWebSocket([ConnectionError("transient upstream failure")])
    sockets = [
        failed,
        *[FakeWebSocket(socket_events([{"type": "session.finished"}])) for _ in range(6)],
    ]
    connector = FakeConnector(sockets)
    service = module.DashScopeRealtimeTTS(api_key="secret", connector=connector)
    monkeypatch.setattr(service, "_preload_retry_delay_seconds", 0.0)

    await service.preload()
    await service.close()

    assert len(connector.calls) == 7
    assert connector.connections[0].closed is True
    assert len(service._sessions) == 0


async def test_preload_classifies_account_standing_failure_as_nonretryable_billing() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    account_error = "Access denied, please make sure your account is in good standing."
    connector = FakeConnector(
        [
            FakeWebSocket(
                [
                    {"type": "session.created", "session": {"id": "session-a"}},
                    ConnectionError(account_error),
                ]
            ),
            FakeWebSocket(
                [
                    {"type": "session.created", "session": {"id": "session-b"}},
                    ConnectionError(account_error),
                ]
            ),
        ]
    )
    service = module.DashScopeRealtimeTTS(api_key="secret", connector=connector)
    service._preload_retry_delay_seconds = 0.0

    with pytest.raises(
        module.DashScopeConnectionError,
        match="account billing is not in good standing",
    ) as exc_info:
        await service.preload()

    assert exc_info.value.category == "billing"
    assert exc_info.value.retryable is False
    assert len(connector.calls) == 1


async def test_different_instructions_use_isolated_hot_connections() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    sockets = [
        FakeWebSocket(socket_events(response_events(b"happy", include_session_finished=True))),
        FakeWebSocket(socket_events(response_events(b"sad", include_session_finished=True))),
    ]
    connector = FakeConnector(sockets)
    service = module.DashScopeRealtimeTTS(api_key="secret", connector=connector)

    assert await collect(service.synthesize_stream("好", instruction="happy")) == [b"happy"]
    assert await collect(service.synthesize_stream("唔", instruction="sad")) == [b"sad"]
    await service.close()

    assert len(connector.calls) == 2
    assert [socket.sent[0]["session"]["instructions"] for socket in sockets] == [
        "happy",
        "sad",
    ]


async def test_invalid_audio_delta_is_a_sanitized_protocol_error() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    socket = FakeWebSocket(
        socket_events(
            [
                {"type": "input_text_buffer.committed"},
                {"type": "response.audio.delta", "delta": "not-base64%%%"},
            ]
        )
    )
    service = module.DashScopeRealtimeTTS(
        api_key="secret",
        connector=FakeConnector([socket]),
    )

    with pytest.raises(module.DashScopeProtocolError, match="audio"):
        await collect(service.synthesize_stream("错误", instruction="neutral"))


async def test_dropped_hot_connection_is_sanitized_and_next_turn_reconnects() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    first = FakeWebSocket(
        [
            {"type": "session.created", "session": {"id": "session-a"}},
            {"type": "session.updated", "session": {"id": "session-a"}},
            ConnectionError("secret upstream address"),
        ]
    )
    second = FakeWebSocket(
        socket_events(response_events(b"recovered", include_session_finished=True))
    )
    connector = FakeConnector([first, second])
    service = module.DashScopeRealtimeTTS(api_key="secret", connector=connector)

    with pytest.raises(module.DashScopeConnectionError, match="connection"):
        await collect(service.synthesize_stream("第一轮", instruction="neutral"))
    recovered = await collect(service.synthesize_stream("第二轮", instruction="neutral"))
    await service.close()

    assert recovered == [b"recovered"]
    assert len(connector.calls) == 2
    assert connector.connections[0].closed is True


async def test_active_stream_uses_idle_timeout_instead_of_total_duration() -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    socket = FakeWebSocket(
        socket_events(
            response_events(b"chunk-0", b"chunk-1", b"chunk-2", include_session_finished=True)
        ),
        receive_delay=0.02,
    )
    service = module.DashScopeRealtimeTTS(
        api_key="secret",
        connector=FakeConnector([socket]),
        timeout_seconds=0.05,
        connect_timeout_seconds=0.5,
    )

    chunks = await collect(service.synthesize_stream("长句", instruction="neutral"))
    await service.close()

    assert chunks == [b"chunk-0", b"chunk-1", b"chunk-2"]


async def test_stream_has_total_watchdog_even_when_nonterminal_events_keep_arriving(
    monkeypatch,
) -> None:
    module = importlib.import_module("animetta.services.tts.dashscope_tts")
    socket = FakeWebSocket(
        socket_events(*[[{"type": "response.created"}] for _ in range(100)]),
        receive_delay=0.01,
    )
    connector = FakeConnector([socket])
    service = module.DashScopeRealtimeTTS(
        api_key="secret",
        connector=connector,
        timeout_seconds=1.0,
        connect_timeout_seconds=0.5,
    )
    monkeypatch.setattr(service, "_max_request_seconds", 0.05)

    with pytest.raises(TimeoutError):
        await collect(service.synthesize_stream("不会结束", instruction="neutral"))

    assert connector.connections[0].closed is True


def test_factory_builds_selected_dashscope_identity_without_network() -> None:
    engine = TTSFactory.create(
        "dashscope",
        strict=True,
        api_key="secret",
        model="qwen3-tts-instruct-flash-realtime",
        voice="Seren",
        base_url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        response_format="pcm",
        sample_rate=24000,
        language_type="Chinese",
        timeout_seconds=20.0,
        connect_timeout_seconds=5.0,
    )
    target = unwrap_tracing_proxy(engine)

    assert type(target).__name__ == "DashScopeRealtimeTTS"
    assert target.provider_identity == "dashscope"
    assert target.model == "qwen3-tts-instruct-flash-realtime"
    assert target.voice == "Seren"
