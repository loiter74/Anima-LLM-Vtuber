from __future__ import annotations

"""
Bilibili Live Danmaku Service

Receives danmaku (bullet comments) from a Bilibili live room using
the bilibili-api-python library. Runs in a separate thread with its
own asyncio event loop to avoid blocking the main server loop.

Usage:
    service = DanmakuService(room_id=123456, sessdata="...")
    service.set_callback(lambda msg: ...)
    service.start()
    # ... later ...
    service.stop()
"""

import asyncio
import contextlib
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from .event_normalizer import normalize_bilibili_event
from .models import DanmakuMessage, LivestreamEvent

if TYPE_CHECKING:
    from .danmaku_buffer import DanmakuBuffer

_AUTH_ERROR_CODES = {-101, -102, -111, -352}
_ROOM_ERROR_CODES = {-400, -404}


def _classify_terminal_error(error: Exception) -> str | None:
    """Map known Bilibili terminal failures without exposing exception text."""
    error_name = type(error).__name__.casefold()
    code = getattr(error, "code", None)
    if code in _AUTH_ERROR_CODES or any(
        marker in error_name
        for marker in ("credential", "sessdata", "unauthorized", "forbidden", "auth")
    ):
        return "Invalid credentials"
    if code in _ROOM_ERROR_CODES or "room" in error_name:
        return "Invalid room"
    return None


class DanmakuService:
    """
    Bilibili live danmaku receiver service.

    Runs bilibili-api's LiveDanmaku in a dedicated thread with its own asyncio
    event loop. Danmaku messages are placed into an asyncio.Queue and consumed
    by the main thread via the provided callback.

    Attributes:
        room_id: Bilibili live room ID to connect to
        sessdata: Optional SESSDATA cookie for authenticated connection
        max_queue_size: Maximum number of queued messages (oldest dropped when exceeded)
        max_retries: Maximum reconnection attempts
    """

    def __init__(
        self,
        room_id: int,
        sessdata: str = "",
        max_queue_size: int = 100,
        max_retries: int = 5,
    ):
        self.room_id = room_id
        self.sessdata = sessdata
        self.max_queue_size = max_queue_size
        self.max_retries = max_retries

        # Threading
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False

        # Queue for cross-thread message passing
        self._queue: asyncio.Queue[LivestreamEvent] = asyncio.Queue(
            maxsize=max_queue_size,
        )

        # Callback set by the consumer (RouteHandlers)
        self._on_danmaku: Callable[[DanmakuMessage], None] | None = None
        self._on_event: Callable[[LivestreamEvent], None] | None = None
        self._on_status_change: Callable[[bool, str], None] | None = None

        # bilibili-api client (created inside the thread)
        self._monitor: Any | None = None

        # DanmakuBuffer for meme collection pipeline
        self._danmaku_buffer: DanmakuBuffer | None = None

        # Connection state
        self._connected = False
        self._reconnect_delay = 1.0  # starts at 1s, doubles each retry
        self._event_sequence = 0
        self._started_monotonic = time.monotonic()

    # ========================================
    # Public API
    # ========================================

    def set_callback(self, callback: Callable[[DanmakuMessage], None]) -> None:
        """Register callback for incoming danmaku messages."""
        self._on_danmaku = callback

    def set_event_callback(
        self,
        callback: Callable[[LivestreamEvent], None],
    ) -> None:
        """Register callback for all normalized livestream events."""
        self._on_event = callback

    def set_status_callback(self, callback: Callable[[bool, str], None]) -> None:
        """Register callback for connection status changes."""
        self._on_status_change = callback

    def set_buffer(self, buffer: DanmakuBuffer) -> None:
        """Attach a DanmakuBuffer to receive copies of all incoming danmaku.

        The buffer receives the same danmaku messages forwarded to the
        on_danmaku callback, enabling the meme collection pipeline to
        consume real-time chat data.
        """
        self._danmaku_buffer = buffer

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Start the Bilibili danmaku service in a background thread."""
        if self._running:
            logger.warning("[DanmakuService] Already running")
            return

        self._running = True
        self._event_sequence = 0
        self._started_monotonic = time.monotonic()
        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="bilibili-danmaku",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"[DanmakuService] Started for room {self.room_id}")

    def stop(self) -> None:
        """Stop the Bilibili danmaku service gracefully."""
        logger.info("[DanmakuService] Stopping...")
        self._running = False

        if self._loop and self._loop.is_running():
            try:
                # Schedule disconnect on the event loop and wake it up
                asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)
            except Exception as e:
                logger.warning(f"[DanmakuService] Error during disconnect: {e}")

        if self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("[DanmakuService] Thread did not stop in time")
            self._thread = None

        self._connected = False
        logger.info("[DanmakuService] Stopped")

    # ========================================
    # Internal: Thread entry point
    # ========================================

    def _run_event_loop(self) -> None:
        """Create and run the asyncio event loop for this thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._run())
        except Exception as exc:
            logger.error(
                "[DanmakuService] Event loop error: error_type={}",
                type(exc).__name__,
            )
        finally:
            self._loop.close()
            self._loop = None

    async def _run(self) -> None:
        """Main async coroutine: connect, listen, and auto-reconnect."""
        retries = 0

        while self._running and retries <= self.max_retries:
            try:
                await self._connect_and_listen()
                # If we get here, connection was cleanly closed
                retries = 0
                self._reconnect_delay = 1.0
            except ImportError:
                logger.error("[DanmakuService] Required dependency unavailable")
                self._notify_status(False, "Dependency unavailable")
                break
            except Exception as exc:
                terminal_status = _classify_terminal_error(exc)
                if terminal_status is not None:
                    logger.error(
                        "[DanmakuService] Terminal connection failure: error_type={}",
                        type(exc).__name__,
                    )
                    self._notify_status(False, terminal_status)
                    break
                retries += 1
                logger.error(
                    "[DanmakuService] Connection error (attempt {}/{}): error_type={}",
                    retries,
                    self.max_retries,
                    type(exc).__name__,
                )

                if not self._running:
                    break

                if retries > self.max_retries:
                    logger.error("[DanmakuService] Max retries reached, giving up")
                    self._notify_status(False, "Max retries reached")
                    break

                # Exponential backoff
                wait = self._reconnect_delay
                self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)
                logger.info(f"[DanmakuService] Reconnecting in {wait:.1f}s...")
                self._notify_status(False, f"Reconnecting in {wait:.1f}s...")
                await asyncio.sleep(wait)

    async def _connect_and_listen(self) -> None:
        """
        Connect to Bilibili live room and listen for danmaku.

        Uses bilibili-api-python's LiveDanmaku class with event callbacks.
        """
        try:
            from bilibili_api import Credential, live
        except ImportError:
            logger.error(
                "[DanmakuService] bilibili-api-python not installed. Run: pip install bilibili-api-python"
            )
            raise

        # Build credential if sessdata is provided
        credential = None
        if self.sessdata:
            credential = Credential(sessdata=self.sessdata)

        # Create LiveDanmaku monitor
        monitor = live.LiveDanmaku(
            room_display_id=self.room_id,
            credential=credential,
            max_retry=3,
        )
        self._monitor = monitor

        # Register event handlers
        @monitor.on("DANMU_MSG")
        async def on_danmaku(event: dict[str, Any]) -> None:
            try:
                await self._queue.put(self._normalize_event("DANMU_MSG", event))
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing DANMU_MSG: {e}")

        @monitor.on("SEND_GIFT")
        async def on_gift(event: dict[str, Any]) -> None:
            try:
                await self._queue.put(self._normalize_event("SEND_GIFT", event))
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing SEND_GIFT: {e}")

        @monitor.on("SUPER_CHAT_MESSAGE")
        async def on_sc(event: dict[str, Any]) -> None:
            try:
                await self._queue.put(
                    self._normalize_event("SUPER_CHAT_MESSAGE", event),
                )
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing SUPER_CHAT: {e}")

        @monitor.on("INTERACT_WORD_V2")
        async def on_interact(event: dict[str, Any]) -> None:
            try:
                await self._queue.put(
                    self._normalize_event("INTERACT_WORD_V2", event),
                )
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing INTERACT_WORD: {e}")

        @monitor.on("LIKE_INFO_V3_CLICK")
        async def on_like_click(event: dict[str, Any]) -> None:
            try:
                await self._queue.put(
                    self._normalize_event("LIKE_INFO_V3_CLICK", event),
                )
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing LIKE click: {e}")

        @monitor.on("LIKE_INFO_V3_UPDATE")
        async def on_like_update(event: dict[str, Any]) -> None:
            try:
                await self._queue.put(
                    self._normalize_event("LIKE_INFO_V3_UPDATE", event),
                )
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing LIKE update: {e}")

        @monitor.on("VIEW")
        async def on_popularity(event: dict[str, Any]) -> None:
            try:
                await self._queue.put(self._normalize_event("VIEW", event))
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing VIEW: {e}")

        known_commands = {
            "DANMU_MSG",
            "SEND_GIFT",
            "SUPER_CHAT_MESSAGE",
            "INTERACT_WORD_V2",
            "LIKE_INFO_V3_CLICK",
            "LIKE_INFO_V3_UPDATE",
            "VIEW",
            "VERIFICATION_SUCCESSFUL",
            "DISCONNECT",
        }

        @monitor.on("ALL")
        async def on_unknown(event: dict[str, Any]) -> None:
            command = str(event.get("type", "UNKNOWN"))
            if command in known_commands:
                return
            try:
                await self._queue.put(self._normalize_event(command, event))
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing unknown event: {e}")

        @monitor.on("DISCONNECT")
        async def on_disconnected(event: dict[str, Any] | object) -> None:
            try:
                payload = event if isinstance(event, dict) else {"data": event}
                await self._queue.put(self._normalize_event("DISCONNECT", payload))
            except Exception as e:
                logger.error(f"[DanmakuService] Error parsing DISCONNECT: {e}")

        @monitor.on("VERIFICATION_SUCCESSFUL")
        async def on_verified(event: dict[str, Any]) -> None:
            self._connected = True
            await self._queue.put(
                self._normalize_event("VERIFICATION_SUCCESSFUL", event),
            )
            self._notify_status(True, "Connected")
            logger.info("[DanmakuService] Connected to room {}", self.room_id)

        # Start consumer task (drains queue → calls callback)
        consumer_task = asyncio.create_task(self._consume_queue())

        try:
            # This blocks until disconnected
            await monitor.connect()
        finally:
            self._connected = False
            self._notify_status(False, "Disconnected")

            # Cancel consumer
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task

            # Clean up monitor
            with contextlib.suppress(Exception):
                await monitor.disconnect()
            self._monitor = None

    # ========================================
    # Internal: Queue consumer
    # ========================================

    async def _consume_queue(self) -> None:
        """
        Drain the message queue and invoke the callback.

        Runs as a background task within the same event loop.
        Messages are forwarded to the main thread via the registered callback.
        """
        while self._running:
            try:
                # Wait for a message with timeout so we can check _running
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)

                # Prefer the unified event callback. The legacy message callback
                # remains the fallback so existing consumers keep their contract.
                message = event.to_danmaku_message()
                if self._on_event:
                    self._on_event(event)
                elif self._on_danmaku and message is not None:
                    self._on_danmaku(message)

                # Push to DanmakuBuffer for meme collection pipeline
                if self._danmaku_buffer and message is not None:
                    self._danmaku_buffer.add(message.text, self.room_id)

                self._queue.task_done()
            except TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[DanmakuService] Queue consumer error: {e}")

    # ========================================
    # Internal: Helpers
    # ========================================

    def _normalize_event(
        self,
        command: str,
        event: dict[str, object],
    ) -> LivestreamEvent:
        """Normalize a protocol event and assign its session timeline."""
        normalized = normalize_bilibili_event(
            command,
            event,
            sequence=self._event_sequence,
            offset_ms=max(
                0,
                int((time.monotonic() - self._started_monotonic) * 1000),
            ),
        )
        self._event_sequence += 1
        return normalized

    async def _disconnect(self) -> None:
        """Disconnect from Bilibili live room."""
        self._connected = False
        if self._monitor:
            try:
                await self._monitor.disconnect()
            except Exception as e:
                logger.debug(f"[DanmakuService] Disconnect error: {e}")
            self._monitor = None

    def _notify_status(self, connected: bool, message: str) -> None:
        """Notify listeners of connection status change."""
        self._connected = connected
        if self._on_status_change:
            self._on_status_change(connected, message)
