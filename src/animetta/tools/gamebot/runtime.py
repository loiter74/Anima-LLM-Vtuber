"""Transport-independent protocol consumed by autonomous game-bot domains."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .contracts import (
    ActionReceipt,
    CapabilityManifest,
    GameBotObservation,
    SkillExecutionResult,
)


@runtime_checkable
class GameBotRuntime(Protocol):
    async def get_capabilities(self) -> CapabilityManifest: ...

    async def observe(self, correlation_id: str) -> GameBotObservation: ...

    async def execute_action(
        self,
        capability: str,
        params: dict[str, Any],
        *,
        session_id: str,
        task_id: str,
        correlation_id: str,
        timeout: float = 60.0,
    ) -> ActionReceipt: ...

    async def eval_skill(
        self,
        code: str,
        *,
        allowed_capabilities: list[str],
        session_id: str,
        task_id: str,
        correlation_id: str,
        timeout: float = 60.0,
    ) -> SkillExecutionResult: ...

    async def cancel_action(self, correlation_id: str) -> dict[str, Any]: ...

    async def health(self) -> dict[str, Any]: ...

    @property
    def is_running(self) -> bool: ...
