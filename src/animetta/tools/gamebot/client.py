"""GameBotClient — high-level client wrapping a GameBotTransport."""

from __future__ import annotations

from typing import Any

from animetta.tools.gamebot.contracts import (
    ActionReceipt,
    CapabilityManifest,
    GameBotObservation,
)
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

    async def send_command(
        self, action: str, params: dict[str, Any], timeout: float = 60.0
    ) -> dict[str, Any]:
        return await self._transport.send_command(action, params, timeout=timeout)

    async def get_status(self) -> dict[str, Any]:
        return await self._transport.send_command("status", {}, timeout=5.0)

    @staticmethod
    def _payload(response: dict[str, Any], action: str) -> Any:
        if response.get("status") != "success":
            raise RuntimeError(f"Game-bot action '{action}' failed: {response.get('result')}")
        return response.get("result")

    async def get_capabilities(self) -> CapabilityManifest:
        response = await self._transport.send_command("capabilities", {}, timeout=5.0)
        return CapabilityManifest.model_validate(self._payload(response, "capabilities"))

    async def observe(self, correlation_id: str) -> GameBotObservation:
        response = await self._transport.send_command(
            "observe", {"correlation_id": correlation_id}, timeout=5.0
        )
        return GameBotObservation.model_validate(self._payload(response, "observe"))

    async def execute_action(
        self,
        capability: str,
        params: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
        correlation_id: str,
        timeout: float = 60.0,
    ) -> ActionReceipt:
        response = await self._transport.send_command(
            "execute_action",
            {
                "capability": capability,
                "params": params,
                "session_id": session_id,
                "task_id": task_id,
                "correlation_id": correlation_id,
            },
            timeout=timeout,
        )
        return ActionReceipt.model_validate(self._payload(response, "execute_action"))

    async def cancel_action(self, correlation_id: str) -> dict[str, Any]:
        response = await self._transport.send_command(
            "cancel_action", {"correlation_id": correlation_id}, timeout=10.0
        )
        payload = self._payload(response, "cancel_action")
        return payload if isinstance(payload, dict) else {"cancelled": bool(payload)}

    async def health(self) -> dict[str, Any]:
        response = await self._transport.send_command("health", {}, timeout=5.0)
        payload = self._payload(response, "health")
        return payload if isinstance(payload, dict) else {"healthy": bool(payload)}

    def on_event(self, callback: Any) -> None:
        self._transport.on_event(callback)

    @property
    def is_running(self) -> bool:
        return self._transport.is_running
