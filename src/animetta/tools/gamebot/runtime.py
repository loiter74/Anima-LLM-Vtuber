"""Transport-independent protocol consumed by autonomous game-bot domains."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .contracts import (
    ActionReceipt,
    CapabilityManifest,
    GameBotObservation,
)
from .contracts.v2 import (
    ActionInspectionRequest,
    ActionRequest,
    ActionStatus,
    CancellationAck,
    CancellationRequest,
    Observation,
    ObservationRequest,
    RegionInspection,
    RegionInspectionRequest,
    RuntimeHealth,
    RuntimeManifest,
)
from .contracts.v2 import (
    ActionReceipt as V2ActionReceipt,
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

    async def cancel_action(self, correlation_id: str) -> dict[str, Any]: ...

    async def health(self) -> dict[str, Any]: ...

    @property
    def is_running(self) -> bool: ...


@runtime_checkable
class GameBotRuntimeV2(Protocol):
    """Production runtime port bound to one validated GameBot v2 instance."""

    async def get_manifest(self) -> RuntimeManifest: ...

    async def observe(self, request: ObservationRequest) -> Observation: ...

    async def inspect_region(self, request: RegionInspectionRequest) -> RegionInspection: ...

    async def execute_action(
        self, request: ActionRequest, *, timeout: float = 60.0
    ) -> V2ActionReceipt: ...

    async def inspect_action(self, request: ActionInspectionRequest) -> ActionStatus: ...

    async def cancel_action(self, request: CancellationRequest) -> CancellationAck: ...

    async def health(self) -> RuntimeHealth: ...

    @property
    def runtime_instance_id(self) -> str | None: ...

    @property
    def is_running(self) -> bool: ...
