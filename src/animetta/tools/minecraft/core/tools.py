"""The complete public Minecraft tool surface: execute, status, and stop."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from langchain_core.tools import tool
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema, JsonSchemaMode

from animetta.tools.minecraft.mission.adaptive import ExplorationFrontier
from animetta.tools.minecraft.mission.models import MissionSpec
from animetta.tools.minecraft.voyager.budget import RequestedBudget
from animetta.tools.minecraft.voyager.gateway import (
    EXECUTE_REQUEST_ADAPTER,
    ExecuteRequest,
)
from animetta.tools.minecraft.voyager.goal_models import AtomicAction

from .assembly import MinecraftControlPlane, assemble_control_plane
from .bridge import MinecraftBridge

_bridge = None
_control_plane: MinecraftControlPlane | None = None
_state_collector = None
_caller_scope: ContextVar[str] = ContextVar("minecraft_caller_scope", default="system:animetta")


class MinecraftExecuteToolInput(BaseModel):
    """Flat discriminated public input without caller-controlled identity."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["2"] = "2"
    kind: Literal["mission", "atomic"]
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:\-]{1,128}$")
    mission: MissionSpec | None = None
    action: AtomicAction | None = None
    requested_budget: RequestedBudget | None = None
    wait_seconds: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_branch(self) -> MinecraftExecuteToolInput:
        EXECUTE_REQUEST_ADAPTER.validate_python(self.model_dump(mode="python", exclude_none=True))
        return self

    @property
    def request(self) -> ExecuteRequest:
        """Return the immutable gateway request represented by this tool input."""

        return EXECUTE_REQUEST_ADAPTER.validate_python(
            self.model_dump(mode="python", exclude_none=True)
        )

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
        *,
        union_format: Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, Any]:
        """Expose the gateway union directly instead of a redundant wrapper."""

        schema = EXECUTE_REQUEST_ADAPTER.json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
            union_format=union_format,
        )
        schema["type"] = "object"
        return schema


@contextmanager
def bind_minecraft_caller_scope(caller_scope: str) -> Iterator[None]:
    """Inject trusted caller identity outside model-generated tool arguments."""

    token = _caller_scope.set(caller_scope)
    try:
        yield
    finally:
        _caller_scope.reset(token)


def init_bridge(config: dict | None = None) -> None:
    """Create the transport-only bridge; lifecycle handlers start it explicitly."""

    global _bridge
    if _bridge is not None:
        return
    from . import bridge as bridge_module
    from .bridge import MinecraftBridge
    from .config import MinecraftConfig

    mc_config = MinecraftConfig(**(config or {}))
    if not mc_config.enabled:
        logger.info("[MinecraftTools] Minecraft gameplay is disabled in config")
        return
    _bridge = MinecraftBridge(mc_config)
    bridge_module._bridge = _bridge
    logger.info("[MinecraftTools] Transport bridge created")


async def configure_voyager_control_plane(
    bridge: MinecraftBridge,
    *,
    event_emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    blueprint_origins: dict[str, tuple[int, int, int]] | None = None,
    entity_origins: dict[str, tuple[int, int, int]] | None = None,
    adaptive_frontier: ExplorationFrontier | None = None,
) -> MinecraftControlPlane:
    """Validate GameBot v2 and assemble exactly one production control plane."""

    global _control_plane
    if _control_plane is not None:
        await _control_plane.close()
    _control_plane = await assemble_control_plane(
        bridge,
        bridge.config,
        event_emit=event_emit,
        blueprint_origins=blueprint_origins,
        entity_origins=entity_origins,
        adaptive_frontier=adaptive_frontier,
    )
    logger.info(
        "[MinecraftTools] GameBot v2 control plane ready: {}",
        _control_plane.adapter.runtime_instance_id,
    )
    return _control_plane


async def cleanup_bridge() -> None:
    """Persist ambiguous work, stop the worker, close stores, then stop transport."""

    global _bridge, _control_plane, _state_collector
    if _control_plane is not None:
        await _control_plane.close()
        _control_plane = None
    if _bridge is not None:
        await _bridge.stop()
        _bridge = None
        from . import bridge as bridge_module

        bridge_module._bridge = None
    _state_collector = None


def _gateway():
    if _control_plane is None:
        raise RuntimeError(
            "Minecraft control plane is not ready; start the bot and validate GameBot v2"
        )
    return _control_plane.gateway


@tool(args_schema=MinecraftExecuteToolInput)
async def mc_execute(
    request_id: str,
    kind: Literal["mission", "atomic"],
    contract_version: Literal["2"] = "2",
    mission: MissionSpec | None = None,
    action: AtomicAction | None = None,
    requested_budget: RequestedBudget | None = None,
    wait_seconds: float = 0,
) -> str:
    """Durably submit one typed Minecraft mission or bounded operator probe.

    Normal conversation must use the `mission` branch. The `atomic` branch is
    reserved for internal/operator probes and must not be synthesized as a hidden
    gameplay plan. The request ID is persistent and idempotent.
    """

    request = MinecraftExecuteToolInput(
        contract_version=contract_version,
        kind=kind,
        request_id=request_id,
        mission=mission,
        action=action,
        requested_budget=requested_budget,
        wait_seconds=wait_seconds,
    ).request
    result = await _gateway().execute(caller_scope=_caller_scope.get(), request=request)
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool
async def mc_status(
    command_id: str | None = None,
    request_id: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    projection_kind: Literal["commands", "missions"] = "commands",
) -> str:
    """Read immediate caller-scoped command/controller projection state.

    This never enters the gameplay queue and never asks the runtime for a fresh
    world observation. Pass at most one of command_id or request_id; use an atomic
    `observe` command when fresh game state is required.
    """

    if command_id and request_id:
        raise ValueError("command_id and request_id are mutually exclusive")
    gateway = _gateway()
    scope = _caller_scope.get()
    if projection_kind == "missions":
        if command_id or request_id:
            raise ValueError("mission projection cannot use command selectors")
        page = await gateway.status_missions(caller_scope=scope, limit=limit, cursor=cursor)
        return json.dumps(page.model_dump(mode="json"), ensure_ascii=False)
    if command_id:
        command = await gateway.status_command(caller_scope=scope, command_id=command_id)
        return json.dumps(command.model_dump(mode="json"), ensure_ascii=False)
    if request_id:
        command = await gateway.status_request(caller_scope=scope, request_id=request_id)
        return json.dumps(command.model_dump(mode="json"), ensure_ascii=False)
    projection = await gateway.status(caller_scope=scope, limit=limit, cursor=cursor)
    return json.dumps(projection.model_dump(mode="json"), ensure_ascii=False)


@tool
async def mc_stop(
    request_id: str,
    reason: str = "operator stop",
    wait_seconds: float = 0,
) -> str:
    """Create an idempotent durable global stop barrier.

    The barrier blocks new execution admission, cancels every pending command,
    records cancellation intent for the active command, and only then signals
    cooperative runtime cancellation. `wait_seconds` is caller waiting metadata.
    """

    del wait_seconds
    result = await _gateway().stop(
        caller_scope=_caller_scope.get(), request_id=request_id, reason=reason
    )
    return json.dumps(
        {
            "stop_command_id": result.stop_command_id,
            "idempotency_reused": result.idempotency_reused,
            "active_command_id": result.active_command_id,
            "cancelled_command_ids": result.cancelled_command_ids,
            "recovery_error": result.recovery_error,
        },
        ensure_ascii=False,
    )


def get_minecraft_tools() -> list[Any]:
    """Return the exact complete public Minecraft LangChain tool surface."""

    return [mc_execute, mc_status, mc_stop]
