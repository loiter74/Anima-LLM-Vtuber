"""Gateway boundary for Bilibili live danmaku transports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .danmaku_service import DanmakuService
from .models import DanmakuMessage

MessageCallback = Callable[[DanmakuMessage], None]
StatusCallback = Callable[[bool, str], None]


class DanmakuGateway(Protocol):
    """Transport contract owned by :class:`LivestreamSession`."""

    room_id: int

    def set_message_callback(self, callback: MessageCallback) -> None:
        """Register the normalized incoming-message callback."""

    def set_status_callback(self, callback: StatusCallback) -> None:
        """Register the normalized connection-status callback."""

    def start(self) -> None:
        """Start the underlying transport."""

    def stop(self) -> None:
        """Stop the underlying transport."""


class _LegacyDanmakuService(Protocol):
    """Narrow interface used to adapt the existing threaded service."""

    def set_callback(self, callback: MessageCallback) -> None: ...

    def set_status_callback(self, callback: StatusCallback) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


LegacyServiceFactory = Callable[..., _LegacyDanmakuService]


class DanmakuServiceGateway:
    """Adapter that keeps the threaded Bilibili client out of session logic."""

    def __init__(
        self,
        room_id: int,
        sessdata: str = "",
        service_factory: LegacyServiceFactory = DanmakuService,
    ) -> None:
        self.room_id = room_id
        self._service = service_factory(room_id=room_id, sessdata=sessdata)

    def set_message_callback(self, callback: MessageCallback) -> None:
        """Forward a normalized message callback to the legacy service."""
        self._service.set_callback(callback)

    def set_status_callback(self, callback: StatusCallback) -> None:
        """Forward a normalized status callback to the legacy service."""
        self._service.set_status_callback(callback)

    def start(self) -> None:
        """Start the adapted service."""
        self._service.start()

    def stop(self) -> None:
        """Stop the adapted service."""
        self._service.stop()


def create_danmaku_gateway(room_id: int, sessdata: str = "") -> DanmakuGateway:
    """Create the production Bilibili transport adapter."""
    return DanmakuServiceGateway(room_id=room_id, sessdata=sessdata)
