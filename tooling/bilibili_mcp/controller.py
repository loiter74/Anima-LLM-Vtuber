"""Socket.IO client for the process-owned Animetta Bilibili session."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any, Protocol
from urllib.parse import urlparse

import socketio

STATUS_EVENT = "bilibili:danmaku_status"
LIVE_EVENT = "bilibili:live_event"
CONNECT_EVENT = "bilibili:connect"
SWITCH_ROOM_EVENT = "bilibili:update_room"
DISCONNECT_EVENT = "bilibili:disconnect"

LIVESTREAM_STATES = frozenset(
    {"stopped", "connecting", "live", "reconnecting", "stopping", "error"}
)
MUTABLE_CONNECT_STATES = frozenset({"stopped", "error"})
IDEMPOTENT_ROOM_STATES = frozenset({"connecting", "live", "reconnecting"})
EVENT_BUFFER_CAPACITY = 200
MAX_EVENT_LIMIT = 100
MAX_WAIT_SECONDS = 60.0

StatusPayload = dict[str, Any]
ToolResult = dict[str, Any]


class SocketIOClient(Protocol):
    """Minimal injectable surface used by the controller."""

    connected: bool

    def on(self, event: str, handler: Callable[..., Awaitable[None]]) -> Any: ...

    async def connect(self, url: str, **kwargs: Any) -> None: ...

    async def disconnect(self) -> None: ...

    async def call(
        self,
        event: str,
        data: dict[str, Any] | None = None,
        timeout: float = 60,
    ) -> Any: ...


def validate_server_url(server_url: str) -> str:
    """Return a normalized loopback HTTP URL or reject it."""
    parsed = urlparse(server_url)
    hostname = parsed.hostname
    if parsed.scheme not in {"http", "https"} or hostname is None:
        raise ValueError("ANIMETTA_MCP_URL 必须是 HTTP URL")
    if hostname.lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("ANIMETTA_MCP_URL 必须指向本机回环地址")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("ANIMETTA_MCP_URL 不得包含凭据")
    if parsed.query or parsed.fragment:
        raise ValueError("ANIMETTA_MCP_URL 不得包含查询参数或片段")
    return server_url.rstrip("/")


def _success(message: str, **payload: Any) -> ToolResult:
    return {"ok": True, "error_code": None, "message": message, **payload}


def _failure(error_code: str, message: str, **payload: Any) -> ToolResult:
    return {"ok": False, "error_code": error_code, "message": message, **payload}


def _generation_id(payload: Mapping[str, Any] | None) -> int | None:
    if payload is None:
        return None
    value = payload.get("generation_id")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class BilibiliController:
    """Operate the single Bilibili session owned by an Animetta backend."""

    def __init__(
        self,
        server_url: str = "http://127.0.0.1",
        *,
        client: SocketIOClient | None = None,
        connection_timeout_seconds: float = 1.0,
    ) -> None:
        self.server_url = validate_server_url(server_url)
        self.client: SocketIOClient = client or socketio.AsyncClient(
            reconnection=True,
            logger=False,
            engineio_logger=False,
        )
        self.connection_timeout_seconds = connection_timeout_seconds
        self._status: StatusPayload | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=EVENT_BUFFER_CAPACITY)
        self._condition = asyncio.Condition()
        self._connection_lock = asyncio.Lock()
        self._transport_connected = bool(getattr(self.client, "connected", False))

        self.client.on(STATUS_EVENT, self._on_status)
        self.client.on(LIVE_EVENT, self._on_live_event)
        self.client.on("disconnect", self._on_transport_disconnect)

    async def close(self) -> None:
        """Close only the local Socket.IO transport, never the live session."""
        if self._transport_connected or bool(getattr(self.client, "connected", False)):
            await self.client.disconnect()
        self._transport_connected = False

    async def get_status(self) -> ToolResult:
        """Return the latest authoritative session snapshot."""
        connection_error = await self._ensure_transport()
        if connection_error is not None:
            return connection_error
        status = await self._wait_for_status(
            states=LIVESTREAM_STATES,
            timeout_seconds=self.connection_timeout_seconds,
        )
        if status is None:
            return _failure(
                "status_unavailable",
                "Animetta 已连接，但未发布 Bilibili 状态",
                status=None,
            )
        return _success("已同步 Bilibili 直播状态", status=status)

    async def connect_room(self, room_id: int, timeout_seconds: float = 30.0) -> ToolResult:
        """Connect from a stopped/error state, with same-room idempotency."""
        invalid = self._validate_command_arguments(room_id, timeout_seconds)
        if invalid is not None:
            return invalid
        current_result = await self.get_status()
        if not current_result["ok"]:
            return current_result
        current = current_result["status"]
        if self._same_room(current, room_id) and current["state"] in IDEMPOTENT_ROOM_STATES:
            return await self._wait_after_idempotent_command(
                room_id=room_id,
                timeout_seconds=timeout_seconds,
            )
        if current["state"] not in MUTABLE_CONNECT_STATES:
            return _failure(
                "invalid_state",
                "直播会话活动期间请使用 bilibili_switch_room",
                status=current,
            )
        return await self._mutate_room(
            event=CONNECT_EVENT,
            room_id=room_id,
            timeout_seconds=timeout_seconds,
            current=current,
        )

    async def switch_room(self, room_id: int, timeout_seconds: float = 30.0) -> ToolResult:
        """Atomically replace the desired room using optimistic concurrency."""
        invalid = self._validate_command_arguments(room_id, timeout_seconds)
        if invalid is not None:
            return invalid
        current_result = await self.get_status()
        if not current_result["ok"]:
            return current_result
        current = current_result["status"]
        if self._same_room(current, room_id) and current["state"] in IDEMPOTENT_ROOM_STATES:
            return await self._wait_after_idempotent_command(
                room_id=room_id,
                timeout_seconds=timeout_seconds,
            )
        return await self._mutate_room(
            event=SWITCH_ROOM_EVENT,
            room_id=room_id,
            timeout_seconds=timeout_seconds,
            current=current,
        )

    async def disconnect_room(self, timeout_seconds: float = 10.0) -> ToolResult:
        """Disconnect the backend-owned session without closing the MCP transport."""
        timeout_error = self._validate_timeout(timeout_seconds)
        if timeout_error is not None:
            return timeout_error
        current_result = await self.get_status()
        if not current_result["ok"]:
            return current_result
        current = current_result["status"]
        if current["state"] == "stopped":
            return _success("Bilibili 直播会话已经停止", status=current)
        expected_generation = _generation_id(current)
        if expected_generation is None:
            return _failure("protocol_error", "Bilibili 状态缺少有效 generation", status=current)
        started_at = asyncio.get_running_loop().time()
        ack_result = await self._send_command(
            DISCONNECT_EVENT,
            {"expected_generation_id": expected_generation},
            timeout_seconds,
        )
        if not ack_result["ok"]:
            return {**ack_result, "status": self._status_copy()}
        remaining = self._remaining_timeout(started_at, timeout_seconds)
        status = await self._wait_for_status(
            states=frozenset({"stopped"}),
            timeout_seconds=remaining,
            minimum_generation=expected_generation + 1,
        )
        if status is None:
            return _failure(
                "timeout",
                "等待 Bilibili 直播会话停止超时",
                status=self._status_copy(),
            )
        return _success("Bilibili 直播会话已停止", status=status)

    async def wait_for_state(self, target_state: str, timeout_seconds: float = 30.0) -> ToolResult:
        """Wait for a state transition using Socket.IO event notifications."""
        if target_state not in LIVESTREAM_STATES:
            return _failure(
                "invalid_state",
                "target_state 必须是已知的 Bilibili 直播状态",
                status=self._status_copy(),
            )
        timeout_error = self._validate_timeout(timeout_seconds)
        if timeout_error is not None:
            return timeout_error
        current_result = await self.get_status()
        if not current_result["ok"]:
            return current_result
        status = await self._wait_for_status(
            states=frozenset({target_state}),
            timeout_seconds=timeout_seconds,
        )
        if status is None:
            return _failure(
                "timeout",
                f"等待 Bilibili 状态“{target_state}”超时",
                status=self._status_copy(),
            )
        return _success(f"Bilibili 已进入“{target_state}”状态", status=status)

    async def get_recent_events(
        self,
        limit: int = 50,
        event_types: Sequence[str] | None = None,
    ) -> ToolResult:
        """Return current-generation normalized events without redaction."""
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_EVENT_LIMIT
        ):
            return _failure(
                "invalid_limit",
                f"limit 必须在 1 到 {MAX_EVENT_LIMIT} 之间",
                events=[],
            )
        if event_types is not None and (
            isinstance(event_types, (str, bytes))
            or any(not isinstance(item, str) or not item for item in event_types)
        ):
            return _failure(
                "invalid_event_types",
                "event_types 必须是非空字符串列表",
                events=[],
            )
        current_result = await self.get_status()
        if not current_result["ok"]:
            return {**current_result, "events": []}
        selected_types = set(event_types) if event_types is not None else None
        async with self._condition:
            matches = [
                deepcopy(event)
                for event in self._events
                if selected_types is None or event.get("event_type") in selected_types
            ]
        return _success(
            "已返回最近的 Bilibili 直播事件",
            status=current_result["status"],
            events=matches[-limit:],
        )

    async def _ensure_transport(self) -> ToolResult | None:
        if self._transport_connected and bool(getattr(self.client, "connected", True)):
            return None
        async with self._connection_lock:
            if self._transport_connected and bool(getattr(self.client, "connected", True)):
                return None
            try:
                await self.client.connect(
                    self.server_url,
                    wait_timeout=self.connection_timeout_seconds,
                )
            except Exception:
                self._transport_connected = False
                return _failure(
                    "backend_unavailable",
                    "无法连接本机 Animetta 后端",
                    status=None,
                )
            self._transport_connected = True
        return None

    async def _mutate_room(
        self,
        *,
        event: str,
        room_id: int,
        timeout_seconds: float,
        current: StatusPayload,
    ) -> ToolResult:
        expected_generation = _generation_id(current)
        if expected_generation is None:
            return _failure("protocol_error", "Bilibili 状态缺少有效 generation", status=current)
        started_at = asyncio.get_running_loop().time()
        ack_result = await self._send_command(
            event,
            {"room_id": room_id, "expected_generation_id": expected_generation},
            timeout_seconds,
        )
        if not ack_result["ok"]:
            return {**ack_result, "status": self._status_copy()}
        remaining = self._remaining_timeout(started_at, timeout_seconds)
        status = await self._wait_for_status(
            states=frozenset({"live", "error"}),
            timeout_seconds=remaining,
            room_id=room_id,
            minimum_generation=expected_generation + 1,
        )
        if status is None:
            return _failure(
                "timeout",
                "等待 Bilibili 房间命令完成超时",
                status=self._status_copy(),
            )
        if status["state"] == "error":
            return _failure(
                str(status.get("error_code") or "session_error"),
                "Bilibili 直播会话进入错误状态",
                status=status,
            )
        return _success("Bilibili 房间已进入直播状态", status=status)

    async def _wait_after_idempotent_command(
        self,
        *,
        room_id: int,
        timeout_seconds: float,
    ) -> ToolResult:
        status = await self._wait_for_status(
            states=frozenset({"live", "error"}),
            timeout_seconds=timeout_seconds,
            room_id=room_id,
        )
        if status is None:
            return _failure(
                "timeout",
                "等待现有 Bilibili 房间命令完成超时",
                status=self._status_copy(),
            )
        if status["state"] == "error":
            return _failure(
                str(status.get("error_code") or "session_error"),
                "Bilibili 直播会话进入错误状态",
                status=status,
            )
        return _success("Bilibili 房间已经处于直播状态", status=status)

    async def _send_command(
        self,
        event: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> ToolResult:
        try:
            ack = await self.client.call(
                event,
                payload,
                timeout=min(timeout_seconds, 5.0),
            )
        except Exception:
            return _failure(
                "backend_unavailable",
                "本机 Animetta 后端未确认命令",
            )
        if not isinstance(ack, Mapping) or not isinstance(ack.get("accepted"), bool):
            return _failure("protocol_error", "Animetta 返回了无效的命令确认")
        if not ack["accepted"]:
            error_code = ack.get("error_code")
            return _failure(
                str(error_code)
                if isinstance(error_code, str) and error_code
                else "command_rejected",
                "Bilibili 命令被拒绝",
            )
        return _success("Bilibili 命令已接受")

    async def _wait_for_status(
        self,
        *,
        states: frozenset[str],
        timeout_seconds: float,
        room_id: int | None = None,
        minimum_generation: int | None = None,
    ) -> StatusPayload | None:
        if timeout_seconds <= 0:
            return None

        def matches() -> bool:
            status = self._status
            if status is None or status.get("state") not in states:
                return False
            if room_id is not None and not self._same_room(status, room_id):
                return False
            generation = _generation_id(status)
            return minimum_generation is None or (
                generation is not None and generation >= minimum_generation
            )

        async with self._condition:
            if matches():
                return deepcopy(self._status)
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(matches),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                return None
            return deepcopy(self._status)

    async def _on_status(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        generation = _generation_id(payload)
        state = payload.get("state")
        if generation is None or state not in LIVESTREAM_STATES:
            return
        async with self._condition:
            previous_generation = _generation_id(self._status)
            if previous_generation != generation or state == "stopped":
                self._events.clear()
            self._status = deepcopy(payload)
            self._condition.notify_all()

    async def _on_live_event(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        generation = _generation_id(payload)
        async with self._condition:
            if generation is None or generation != _generation_id(self._status):
                return
            self._events.append(deepcopy(payload))

    async def _on_transport_disconnect(self, *_args: Any) -> None:
        self._transport_connected = False
        async with self._condition:
            self._condition.notify_all()

    def _validate_command_arguments(
        self,
        room_id: object,
        timeout_seconds: float,
    ) -> ToolResult | None:
        if isinstance(room_id, bool) or not isinstance(room_id, int) or room_id <= 0:
            return _failure("invalid_room_id", "room_id 必须是正整数", status=None)
        return self._validate_timeout(timeout_seconds)

    def _validate_timeout(self, timeout_seconds: object) -> ToolResult | None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= MAX_WAIT_SECONDS
        ):
            return _failure(
                "invalid_timeout",
                f"timeout_seconds 必须大于 0 且不超过 {int(MAX_WAIT_SECONDS)}",
                status=self._status_copy(),
            )
        return None

    def _same_room(self, status: Mapping[str, Any], room_id: int) -> bool:
        return status.get("desired_room_id") == room_id or (
            status.get("desired_room_id") is None and status.get("room_id") == room_id
        )

    def _status_copy(self) -> StatusPayload | None:
        return deepcopy(self._status)

    def _remaining_timeout(self, started_at: float, timeout_seconds: float) -> float:
        elapsed = asyncio.get_running_loop().time() - started_at
        return max(0.0, timeout_seconds - elapsed)
