"""Typed GameBot v2 adapter over the Minecraft process transport."""

from __future__ import annotations

from typing import Any, TypeVar

from animetta.tools.gamebot.contracts.v2 import (
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
    RuntimeProtocolError,
)
from animetta.tools.gamebot.contracts.v2.receipts import ActionReceipt

ContractT = TypeVar("ContractT")


class GameBotRuntimeError(RuntimeError):
    """Exception wrapper retaining the machine-readable v2 error envelope."""

    def __init__(self, error: RuntimeProtocolError) -> None:
        super().__init__(f"{error.code}: {error.message}")
        self.error = error


class MinecraftGameBotV2Adapter:
    """Validate and bind mc-mcp messages to one GameBot v2 instance."""

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge
        self._manifest: RuntimeManifest | None = None

    @property
    def runtime_instance_id(self) -> str | None:
        return self._manifest.runtime_instance_id if self._manifest else None

    @property
    def is_running(self) -> bool:
        return bool(self._bridge.is_running)

    @staticmethod
    def _error(action: str, result: object) -> GameBotRuntimeError:
        payload = result if isinstance(result, dict) else {}
        return GameBotRuntimeError(
            RuntimeProtocolError(
                code=str(payload.get("code", "RUNTIME_ERROR")),
                message=str(payload.get("message", result)),
                phase="runtime",
                outcome_known=False,
                world_may_have_changed=action == "gamebot_v2_execute_action",
                caller_may_resubmit=False,
                operator_action="inspect runtime health and reconcile before retrying",
                details=payload.get("details", {})
                if isinstance(payload.get("details", {}), dict)
                else {},
            )
        )

    @classmethod
    def _payload(cls, response: dict[str, Any], action: str) -> Any:
        if response.get("status") != "success":
            raise cls._error(action, response.get("result"))
        return response.get("result")

    def _require_bound(self, runtime_instance_id: str) -> None:
        expected = self.runtime_instance_id
        if expected is None:
            raise GameBotRuntimeError(
                RuntimeProtocolError(
                    code="RUNTIME_NOT_READY",
                    message="GameBot v2 manifest has not been validated",
                    phase="admission",
                    outcome_known=True,
                    world_may_have_changed=False,
                    caller_may_resubmit=True,
                    operator_action="validate the runtime manifest before admission",
                )
            )
        if runtime_instance_id != expected:
            raise GameBotRuntimeError(
                RuntimeProtocolError(
                    code="RUNTIME_INSTANCE_CHANGED",
                    message=(
                        f"Request targets runtime {runtime_instance_id}; active runtime is {expected}"
                    ),
                    phase="admission",
                    outcome_known=False,
                    world_may_have_changed=False,
                    caller_may_resubmit=False,
                    operator_action="reconcile against the active runtime instance",
                    details={"expected": expected, "actual": runtime_instance_id},
                )
            )

    def _validate_result_instance(self, runtime_instance_id: str) -> None:
        self._require_bound(runtime_instance_id)

    async def get_manifest(self) -> RuntimeManifest:
        response = await self._bridge.send_command("gamebot_v2_manifest", {}, timeout=5.0)
        manifest = RuntimeManifest.model_validate(self._payload(response, "gamebot_v2_manifest"))
        self._manifest = manifest
        return manifest

    async def observe(self, request: ObservationRequest) -> Observation:
        self._require_bound(request.runtime_instance_id)
        response = await self._bridge.send_command(
            "gamebot_v2_observe", request.model_dump(mode="json"), timeout=5.0
        )
        result = Observation.model_validate(self._payload(response, "gamebot_v2_observe"))
        self._validate_result_instance(result.runtime_instance_id)
        return result

    async def execute_action(
        self, request: ActionRequest, *, timeout: float = 60.0
    ) -> ActionReceipt:
        self._require_bound(request.runtime_instance_id)
        response = await self._bridge.send_command(
            "gamebot_v2_execute_action",
            request.model_dump(mode="json"),
            timeout=timeout,
        )
        result = ActionReceipt.model_validate(self._payload(response, "gamebot_v2_execute_action"))
        self._validate_result_instance(result.runtime_instance_id)
        return result

    async def inspect_region(self, request: RegionInspectionRequest) -> RegionInspection:
        """Run the bounded read-only region projection through the v2 transport."""

        self._require_bound(request.runtime_instance_id)
        response = await self._bridge.send_command(
            "gamebot_v2_inspect_region",
            request.model_dump(mode="json"),
            timeout=10.0,
        )
        result = RegionInspection.model_validate(
            self._payload(response, "gamebot_v2_inspect_region")
        )
        self._validate_result_instance(result.runtime_instance_id)
        return result

    async def inspect_action(self, request: ActionInspectionRequest) -> ActionStatus:
        self._require_bound(request.runtime_instance_id)
        response = await self._bridge.send_command(
            "gamebot_v2_inspect_action", request.model_dump(mode="json"), timeout=5.0
        )
        result = ActionStatus.model_validate(self._payload(response, "gamebot_v2_inspect_action"))
        self._validate_result_instance(result.runtime_instance_id)
        return result

    async def cancel_action(self, request: CancellationRequest) -> CancellationAck:
        self._require_bound(request.runtime_instance_id)
        response = await self._bridge.send_command(
            "gamebot_v2_cancel_action", request.model_dump(mode="json"), timeout=10.0
        )
        result = CancellationAck.model_validate(self._payload(response, "gamebot_v2_cancel_action"))
        self._validate_result_instance(result.runtime_instance_id)
        return result

    async def health(self) -> RuntimeHealth:
        response = await self._bridge.send_command("gamebot_v2_health", {}, timeout=5.0)
        result = RuntimeHealth.model_validate(self._payload(response, "gamebot_v2_health"))
        self._validate_result_instance(result.runtime_instance_id)
        return result
