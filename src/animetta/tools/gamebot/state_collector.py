"""Generic state collector — polls bot status and forwards to an emitter callback."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from loguru import logger

from .client import GameBotClient


class GameBotStateCollector:
    """Periodically polls ``GameBotClient.get_status()`` and emits state to a callback.

    Does NOT import Minecraft-specific code (HUD, Socket.IO events, etc.).
    Minecraft wrapper keeps those responsibilities.
    """

    def __init__(
        self,
        client: GameBotClient,
        interval: float = 2.0,
        on_state: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._client = client
        self._interval = interval
        self._on_state = on_state
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[GameBotStateCollector] Started (interval={self._interval}s)")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("[GameBotStateCollector] Stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._poll_and_emit()
            except Exception:
                logger.debug("[GameBotStateCollector] Cycle error", exc_info=True)
            await asyncio.sleep(self._interval)

    async def _poll_and_emit(self) -> None:
        """Poll status once and forward to the emitter callback."""
        resp = await self._client.get_status()
        if not isinstance(resp, dict) or resp.get("status") != "success":
            return
        data = resp.get("result", {})
        if self._on_state:
            self._on_state(data)
