"""Gamebot transport protocol — abstract interface for bot communication."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GameBotTransport(Protocol):
    """Protocol for communicating with a game bot runtime.

    Implementations handle the physical transport (stdio, HTTP, WebSocket, etc.)
    while this protocol defines the transport-agnostic contract.
    """

    async def start(self, login_timeout: float = 15.0) -> None:
        """Launch or connect to the bot runtime. Must emit a login event on success."""
        ...

    async def stop(self) -> None:
        """Gracefully stop the bot runtime."""
        ...

    async def send_command(self, action: str, params: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        """Send a command and wait for a response. Returns bridge-style dict."""
        ...

    def on_event(self, callback: Any) -> None:
        """Register a callback for async events from the runtime."""
        ...

    @property
    def is_running(self) -> bool:
        """Whether the runtime is currently active."""
        ...
