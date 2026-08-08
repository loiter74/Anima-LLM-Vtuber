"""Anonymous live capture backed by the production Bilibili service."""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from animetta.services.bilibili import LivestreamEvent
from animetta.services.bilibili.danmaku_service import DanmakuService

from .dataset import DatasetWriter


class CaptureDependencyError(RuntimeError):
    """Raised before capture when the optional protocol stack is unavailable."""


class CaptureService(Protocol):
    """Small surface used by the anonymous collector."""

    def set_event_callback(self, callback: Callable[[LivestreamEvent], None]) -> None: ...

    def set_status_callback(self, callback: Callable[[bool, str], None]) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


def require_capture_dependencies(
    *,
    import_module: Callable[[str], Any] = importlib.import_module,
) -> None:
    """Fail before opening a room when the locked optional stack is absent."""
    try:
        import_module("bilibili_api")
        import_module("aiohttp")
    except (ImportError, ModuleNotFoundError) as exc:
        raise CaptureDependencyError(
            "Live capture dependencies are unavailable. "
            "Install them with: pip install -r requirements-dev.txt",
        ) from exc


class AnonymousLivestreamCollector:
    """Capture a public room with no account credential and sanitize immediately."""

    def __init__(
        self,
        *,
        room_id: int,
        writer: DatasetWriter,
        duration_seconds: float,
        service_factory: Callable[[int, str], CaptureService] = DanmakuService,
        monotonic: Callable[[], float] = time.monotonic,
        waiter: Callable[[float], bool] | None = None,
        dependency_check: Callable[[], None] = require_capture_dependencies,
    ) -> None:
        if room_id <= 0:
            raise ValueError("room_id must be positive")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        self._room_id = room_id
        self._writer = writer
        self._duration_seconds = duration_seconds
        self._service_factory = service_factory
        self._monotonic = monotonic
        self._stop_event = threading.Event()
        self._waiter = waiter or self._stop_event.wait
        self._dependency_check = dependency_check
        self._service: CaptureService | None = None
        self._terminal_error: str | None = None

    def capture(self) -> dict[str, Any]:
        """Block for the configured duration, then close and checksum the dataset."""
        self._dependency_check()
        self._stop_event.clear()
        self._terminal_error = None
        service = self._service_factory(self._room_id, "")
        self._service = service
        service.set_event_callback(self._writer.write)
        service.set_status_callback(self._on_status)
        started = self._monotonic()
        service.start()
        try:
            while not self._stop_event.is_set():
                elapsed = self._monotonic() - started
                remaining = self._duration_seconds - elapsed
                if remaining <= 0:
                    break
                if self._waiter(min(1.0, remaining)):
                    break
        finally:
            service.stop()
            self._service = None
        if self._terminal_error is not None:
            raise RuntimeError(self._terminal_error)
        return self._writer.finalize(
            duration_ms=max(1, int(self._duration_seconds * 1000)),
        )

    def stop(self) -> None:
        """Request bounded capture shutdown from another thread."""
        self._stop_event.set()

    def _on_status(self, connected: bool, message: str) -> None:
        if connected:
            return
        if message in {"Dependency unavailable", "Invalid credentials", "Invalid room"}:
            self._terminal_error = message
            self._stop_event.set()
