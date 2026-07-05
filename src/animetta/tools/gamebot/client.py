"""GameBotClient — high-level client wrapping a GameBotTransport."""

from __future__ import annotations

from typing import Any

from animetta.tools.gamebot.transport import GameBotTransport


class GameBotClient:
    """Thin wrapper around a GameBotTransport providing convenience methods.

    This is the primary interface for Anima code to interact with a game bot runtime.
    """

    def __init__(self, transport: GameBotTransport) -> None:
        self._transport = transport

    async def start(self, login_timeout: float = 15.0) -> None:
        await self._transport.start(login_timeout=login_timeout)

    async def stop(self) -> None:
        await self._transport.stop()

    async def send_command(self, action: str, params: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        return await self._transport.send_command(action, params, timeout=timeout)

    async def get_status(self) -> dict[str, Any]:
        return await self._transport.send_command("status", {}, timeout=5.0)

    def on_event(self, callback: Any) -> None:
        self._transport.on_event(callback)

    @property
    def is_running(self) -> bool:
        return self._transport.is_running
