"""Unit tests for the Socket.IO Bilibili controller."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from tooling.bilibili_mcp.controller import (
    CONNECT_EVENT,
    DISCONNECT_EVENT,
    LIVE_EVENT,
    STATUS_EVENT,
    SWITCH_ROOM_EVENT,
    BilibiliController,
    validate_server_url,
)

Handler = Callable[..., Awaitable[None]]
CommandHook = Callable[[str, dict[str, Any] | None], Awaitable[dict[str, Any]]]


def status(
    state: str,
    generation_id: int,
    *,
    room_id: int | None = None,
    desired_room_id: int | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "connected": state in {"prelive", "live"},
        "room_id": room_id,
        "desired_room_id": desired_room_id,
        "retry_count": 0,
        "error_code": error_code,
        "generation_id": generation_id,
        "message": state,
        "updated_at": float(generation_id),
    }


class FakeSocketIOClient:
    def __init__(
        self,
        initial_status: dict[str, Any] | None,
        *,
        connect_error: Exception | None = None,
    ) -> None:
        self.initial_status = initial_status
        self.connect_error = connect_error
        self.connected = False
        self.handlers: dict[str, Handler] = {}
        self.calls: list[tuple[str, dict[str, Any] | None, float]] = []
        self.connect_kwargs: dict[str, Any] = {}
        self.command_hook: CommandHook | None = None

    def on(self, event: str, handler: Handler) -> Handler:
        self.handlers[event] = handler
        return handler

    async def connect(self, url: str, **kwargs: Any) -> None:
        assert url.startswith("http://127.0.0.1")
        assert kwargs["wait_timeout"] <= 1.0
        self.connect_kwargs = kwargs
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True
        if self.initial_status is not None:
            await self.push(STATUS_EVENT, self.initial_status)

    async def disconnect(self) -> None:
        self.connected = False
        await self.handlers["disconnect"]()

    async def call(
        self,
        event: str,
        data: dict[str, Any] | None = None,
        timeout: float = 60,
    ) -> dict[str, Any]:
        self.calls.append((event, data, timeout))
        if self.command_hook is None:
            return {
                "accepted": True,
                "state": "connecting",
                "error_code": None,
                "message": "Command accepted",
            }
        return await self.command_hook(event, data)

    async def push(self, event: str, payload: dict[str, Any]) -> None:
        await self.handlers[event](payload)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "ftp://127.0.0.1",
        "http://user:secret@127.0.0.1",
        "http://127.0.0.1?token=secret",
    ],
)
def test_server_url_rejects_non_loopback_or_credentialed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_server_url(url)


def test_server_url_accepts_loopback_hosts() -> None:
    assert validate_server_url("http://127.0.0.1/") == "http://127.0.0.1"
    assert validate_server_url("https://localhost:8443") == "https://localhost:8443"
    assert validate_server_url("http://[::1]:8080") == "http://[::1]:8080"


async def test_get_status_reports_backend_unavailable_without_exception_details() -> None:
    client = FakeSocketIOClient(None, connect_error=RuntimeError("SESSDATA=top-secret"))
    controller = BilibiliController(client=client)

    result = await controller.get_status()

    assert result == {
        "ok": False,
        "error_code": "backend_unavailable",
        "message": "无法连接本机 Animetta 后端",
        "status": None,
    }
    assert "SESSDATA" not in repr(result)


async def test_transport_uses_access_token_as_socket_auth_without_exposing_it() -> None:
    access_token = "private-access-token-that-is-long-enough"
    client = FakeSocketIOClient(status("stopped", 0))
    controller = BilibiliController(client=client, access_token=access_token)

    result = await controller.get_status()

    assert result["ok"] is True
    assert client.connect_kwargs["auth"] == {"token": access_token}
    assert access_token not in repr(controller)


async def test_connect_sends_generation_and_accepts_prelive() -> None:
    client = FakeSocketIOClient(status("stopped", 0))
    controller = BilibiliController(client=client)

    async def command(event: str, data: dict[str, Any] | None) -> dict[str, Any]:
        assert event == CONNECT_EVENT
        assert data == {"room_id": 2233, "expected_generation_id": 0}
        await client.push(
            STATUS_EVENT,
            status("prelive", 1, room_id=2233, desired_room_id=2233),
        )
        return {"accepted": True, "state": "connecting", "error_code": None, "message": "ok"}

    client.command_hook = command
    result = await controller.connect_room(2233)

    assert result["ok"] is True
    assert result["status"]["state"] == "prelive"
    assert client.calls[0][0] == CONNECT_EVENT
    assert "SESSDATA" not in repr(client.calls)


async def test_connect_same_live_room_is_idempotent() -> None:
    client = FakeSocketIOClient(status("live", 4, room_id=2233, desired_room_id=2233))
    controller = BilibiliController(client=client)

    result = await controller.connect_room(2233)

    assert result["ok"] is True
    assert client.calls == []


async def test_connect_retries_same_room_from_error_state() -> None:
    client = FakeSocketIOClient(
        status("error", 4, desired_room_id=2233, error_code="gateway_error")
    )
    controller = BilibiliController(client=client)

    async def command(event: str, data: dict[str, Any] | None) -> dict[str, Any]:
        assert event == CONNECT_EVENT
        assert data == {"room_id": 2233, "expected_generation_id": 4}
        await client.push(
            STATUS_EVENT,
            status("live", 5, room_id=2233, desired_room_id=2233),
        )
        return {"accepted": True, "state": "connecting", "error_code": None, "message": "ok"}

    client.command_hook = command
    result = await controller.connect_room(2233)

    assert result["ok"] is True
    assert len(client.calls) == 1


async def test_switch_room_surfaces_stale_generation_without_retry() -> None:
    client = FakeSocketIOClient(status("live", 5, room_id=100, desired_room_id=100))
    controller = BilibiliController(client=client)

    async def reject(event: str, data: dict[str, Any] | None) -> dict[str, Any]:
        assert event == SWITCH_ROOM_EVENT
        assert data == {"room_id": 200, "expected_generation_id": 5}
        return {
            "accepted": False,
            "state": "live",
            "error_code": "stale_generation",
            "message": "Stale generation",
        }

    client.command_hook = reject
    result = await controller.switch_room(200)

    assert result["ok"] is False
    assert result["error_code"] == "stale_generation"
    assert len(client.calls) == 1


async def test_disconnect_sends_generation_and_waits_for_stopped() -> None:
    client = FakeSocketIOClient(status("live", 2, room_id=100, desired_room_id=100))
    controller = BilibiliController(client=client)

    async def command(event: str, data: dict[str, Any] | None) -> dict[str, Any]:
        assert event == DISCONNECT_EVENT
        assert data == {"expected_generation_id": 2}
        await client.push(STATUS_EVENT, status("stopped", 3))
        return {"accepted": True, "state": "stopping", "error_code": None, "message": "ok"}

    client.command_hook = command
    result = await controller.disconnect_room()

    assert result["ok"] is True
    assert result["status"]["state"] == "stopped"


async def test_event_buffer_is_bounded_filterable_and_generation_scoped() -> None:
    client = FakeSocketIOClient(status("live", 7, room_id=42, desired_room_id=42))
    controller = BilibiliController(client=client)
    await controller.get_status()

    for sequence in range(205):
        await client.push(
            LIVE_EVENT,
            {
                "room_id": 42,
                "generation_id": 7,
                "sequence": sequence,
                "offset_ms": sequence * 10,
                "event_type": "gift" if sequence % 2 else "danmaku",
                "actor_id": f"bilibili:{sequence}",
                "text": f"原文-{sequence}",
                "payload": {
                    "user_name": f"观众-{sequence}",
                    "user_id": sequence,
                    "gift": {"name": "辣条", "count": 1},
                },
            },
        )

    result = await controller.get_recent_events(limit=100, event_types=["gift"])

    assert result["ok"] is True
    assert len(result["events"]) == 100
    assert result["events"][0]["sequence"] == 5
    assert result["events"][-1]["payload"]["user_name"] == "观众-203"

    await client.push(STATUS_EVENT, status("live", 8, room_id=43, desired_room_id=43))
    await client.push(
        LIVE_EVENT,
        {
            "room_id": 42,
            "generation_id": 7,
            "sequence": 999,
            "offset_ms": 1,
            "event_type": "danmaku",
            "actor_id": "bilibili:old",
            "text": "旧房间",
            "payload": {},
        },
    )
    cleared = await controller.get_recent_events()

    assert cleared["events"] == []


async def test_wait_for_state_uses_notification_and_times_out_cleanly() -> None:
    client = FakeSocketIOClient(status("connecting", 1, desired_room_id=10))
    controller = BilibiliController(client=client)
    await controller.get_status()

    result = await controller.wait_for_state("live", timeout_seconds=0.01)

    assert result["ok"] is False
    assert result["error_code"] == "timeout"


async def test_invalid_arguments_are_structured() -> None:
    client = FakeSocketIOClient(status("stopped", 0))
    controller = BilibiliController(client=client)

    assert (await controller.connect_room(0))["error_code"] == "invalid_room_id"
    assert (await controller.wait_for_state("unknown"))["error_code"] == "invalid_state"
    assert (await controller.get_recent_events(limit=101))["error_code"] == "invalid_limit"
    assert (await controller.get_recent_events(event_types=[""]))["error_code"] == (
        "invalid_event_types"
    )
