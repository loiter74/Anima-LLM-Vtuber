"""MinecraftBridge adapter for the transport-independent game-bot runtime."""

from __future__ import annotations

from typing import Any

from animetta.tools.gamebot.contracts import (
    ActionReceipt,
    CapabilityManifest,
    GameBotObservation,
    SkillExecutionResult,
)


class MinecraftGameBotAdapter:
    """Expose a MinecraftBridge through the typed GameBotRuntime boundary."""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge

    @staticmethod
    def _payload(response: dict[str, Any], action: str) -> Any:
        if response.get("status") != "success":
            result = response.get("result")
            if isinstance(result, dict):
                code = str(result.get("code", "RUNTIME_ERROR"))
                message = str(result.get("message", ""))
                raise RuntimeError(f"{action} failed [{code}]: {message}")
            raise RuntimeError(f"{action} failed [RUNTIME_ERROR]: {result}")
        return response.get("result")

    async def get_capabilities(self) -> CapabilityManifest:
        response = await self._bridge.send_command("capabilities", {}, timeout=5.0)
        return CapabilityManifest.model_validate(self._payload(response, "capabilities"))

    async def observe(self, correlation_id: str) -> GameBotObservation:
        response = await self._bridge.send_command(
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
        response = await self._bridge.send_command(
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

    async def eval_skill(
        self,
        code: str,
        *,
        allowed_capabilities: list[str],
        session_id: str,
        task_id: str,
        correlation_id: str,
        timeout: float = 60.0,
    ) -> SkillExecutionResult:
        response = await self._bridge.send_command(
            "eval_skill",
            {
                "code": code,
                "allowed_capabilities": allowed_capabilities,
                "session_id": session_id,
                "task_id": task_id,
                "correlation_id": correlation_id,
            },
            timeout=timeout,
        )
        return SkillExecutionResult.model_validate(self._payload(response, "eval_skill"))

    async def cancel_action(self, correlation_id: str) -> dict[str, Any]:
        response = await self._bridge.send_command(
            "cancel_action", {"correlation_id": correlation_id}, timeout=10.0
        )
        payload = self._payload(response, "cancel_action")
        return payload if isinstance(payload, dict) else {"cancelled": bool(payload)}

    async def health(self) -> dict[str, Any]:
        response = await self._bridge.send_command("health", {}, timeout=5.0)
        payload = self._payload(response, "health")
        return payload if isinstance(payload, dict) else {"healthy": bool(payload)}

    @property
    def is_running(self) -> bool:
        return bool(self._bridge.is_running)
