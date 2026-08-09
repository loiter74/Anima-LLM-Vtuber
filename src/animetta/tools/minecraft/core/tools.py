"""The complete public Minecraft capability surface: connection and bot operation."""

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
from animetta.tools.minecraft.mission.projection import MissionProjectionService
from animetta.tools.minecraft.mission.repository import SQLiteMissionRepository
from animetta.tools.minecraft.voyager.budget import RequestedBudget
from animetta.tools.minecraft.voyager.gateway import EXECUTE_REQUEST_ADAPTER, ExecuteRequest
from animetta.tools.minecraft.voyager.goal_models import AtomicAction
from animetta.tools.minecraft.voyager.sqlite_repository import SQLiteCommandJournal

from .assembly import MinecraftControlPlane, assemble_control_plane
from .bridge import MinecraftMcpBridge
from .config import MinecraftConfig

_bridge: MinecraftMcpBridge | None = None
_control_plane: MinecraftControlPlane | None = None
_caller_scope: ContextVar[str] = ContextVar("minecraft_caller_scope", default="system:animetta")


class MinecraftExecuteRequest(BaseModel):
    """Existing typed mission/atomic request nested under mc_operate_bot.execute."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["2"] = "2"
    kind: Literal["mission", "atomic"]
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:\-]{1,128}$")
    mission: MissionSpec | None = None
    action: AtomicAction | None = None
    requested_budget: RequestedBudget | None = None
    wait_seconds: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_branch(self) -> MinecraftExecuteRequest:
        EXECUTE_REQUEST_ADAPTER.validate_python(self.model_dump(mode="python", exclude_none=True))
        return self

    @property
    def request(self) -> ExecuteRequest:
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
        schema = EXECUTE_REQUEST_ADAPTER.json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
            union_format=union_format,
        )
        schema["type"] = "object"
        return schema


class MinecraftConnectionToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["connect", "status", "disconnect", "shutdown", "reattach_viewer"]
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:\-]{1,128}$")
    profile: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _profile_only_for_connect(self) -> MinecraftConnectionToolInput:
        if self.operation != "connect" and self.profile is not None:
            raise ValueError("profile is only valid for connect")
        return self


class MinecraftOperateToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["execute", "progress", "cancel"]
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:\-]{1,128}$")
    execute: MinecraftExecuteRequest | None = None
    command_id: str | None = None
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    projection_kind: Literal["commands", "missions"] = "commands"
    reason: str = Field(default="operator stop", min_length=1, max_length=256)

    @model_validator(mode="after")
    def _validate_operation(self) -> MinecraftOperateToolInput:
        if self.operation == "execute":
            if (
                self.execute is None
                or any((self.command_id, self.cursor))
                or self.limit != 20
                or self.projection_kind != "commands"
                or self.reason != "operator stop"
            ):
                raise ValueError("execute only accepts the execute payload")
            if self.request_id is not None and self.request_id != self.execute.request.request_id:
                raise ValueError("execute request_id must match execute.request_id")
        elif self.operation == "progress":
            if self.execute is not None or self.reason != "operator stop":
                raise ValueError("progress cannot include execute or reason")
            if self.command_id and self.request_id:
                raise ValueError("command_id and request_id are mutually exclusive")
            if self.projection_kind == "missions" and (self.command_id or self.request_id):
                raise ValueError("mission progress cannot use command selectors")
        else:
            if (
                self.request_id is None
                or self.execute is not None
                or any((self.command_id, self.cursor))
                or self.limit != 20
                or self.projection_kind != "commands"
            ):
                raise ValueError("cancel only accepts request_id and reason")
        return self


@contextmanager
def bind_minecraft_caller_scope(caller_scope: str) -> Iterator[None]:
    token = _caller_scope.set(caller_scope)
    try:
        yield
    finally:
        _caller_scope.reset(token)


def init_bridge(config: dict[str, Any] | None = None) -> None:
    """Create the MCP client without starting mc-mcp or any Minecraft resource."""

    global _bridge
    if _bridge is not None:
        return
    mc_config = MinecraftConfig(**(config or {}))
    if not mc_config.enabled:
        logger.info("[MinecraftTools] Minecraft gameplay is disabled in config")
        return
    _bridge = MinecraftMcpBridge(mc_config)
    from . import bridge as bridge_module

    bridge_module._bridge = _bridge
    logger.info("[MinecraftTools] mc-mcp client created")


async def configure_voyager_control_plane(
    bridge: MinecraftMcpBridge,
    *,
    event_emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    blueprint_origins: dict[str, tuple[int, int, int]] | None = None,
    entity_origins: dict[str, tuple[int, int, int]] | None = None,
    adaptive_frontier: ExplorationFrontier | None = None,
) -> MinecraftControlPlane:
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
    """Close Anima-owned state and transport without stopping MC resources."""

    global _bridge, _control_plane
    await _close_control_plane()
    if _bridge is not None:
        await _bridge.close()
        _bridge = None
        from . import bridge as bridge_module

        bridge_module._bridge = None


async def manage_minecraft_connection(
    operation: Literal["connect", "status", "disconnect", "shutdown", "reattach_viewer"],
    *,
    request_id: str,
    profile: str | None = None,
    event_emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    bridge = _require_bridge()
    if operation == "connect":
        result = await bridge.start(profile=profile, request_id=request_id)
        try:
            await configure_voyager_control_plane(bridge, event_emit=event_emit)
        except Exception:
            try:
                await bridge.disconnect_runtime(request_id=f"{request_id}:rollback")
            except Exception:
                logger.exception(
                    "[MinecraftTools] failed to disconnect bot after control-plane assembly error"
                )
            raise
        return result
    if operation == "status":
        return await bridge.connection_status()
    if operation == "reattach_viewer":
        return await bridge.reattach_viewer(request_id=request_id)
    await _stop_control_plane(request_id=request_id, reason=f"connection {operation}")
    await _close_control_plane()
    if operation == "disconnect":
        return await bridge.disconnect_runtime(request_id=request_id)
    return await bridge.shutdown_runtime(request_id=request_id)


@tool(args_schema=MinecraftConnectionToolInput)
async def mc_connection(
    operation: Literal["connect", "status", "disconnect", "shutdown", "reattach_viewer"],
    request_id: str,
    profile: str | None = None,
) -> str:
    """管理 Minecraft 服务端、bot 与 viewer 的连接生命周期。

    connect 使用 mc-mcp profile；disconnect 仅断开 bot；shutdown 只关闭 mc-mcp
    拥有的托管服务端；reattach_viewer 请求 MC 侧重新自动附身。
    """

    result = await manage_minecraft_connection(
        operation,
        request_id=request_id,
        profile=profile,
    )
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=MinecraftOperateToolInput)
async def mc_operate_bot(
    operation: Literal["execute", "progress", "cancel"],
    request_id: str | None = None,
    execute: MinecraftExecuteRequest | None = None,
    command_id: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    projection_kind: Literal["commands", "missions"] = "commands",
    reason: str = "operator stop",
) -> str:
    """提交 typed Minecraft 任务、读取持久化进度或取消全部 bot 行动。

    普通对话使用 execute 的 mission 分支；atomic 仅供受信任的内部探针使用。
    progress 不查询实时世界；cancel 先提交 durable stop barrier 再协作取消 runtime。
    """

    validated = MinecraftOperateToolInput(
        operation=operation,
        request_id=request_id,
        execute=execute,
        command_id=command_id,
        cursor=cursor,
        limit=limit,
        projection_kind=projection_kind,
        reason=reason,
    )
    scope = _caller_scope.get()
    if validated.operation == "execute":
        gateway = _gateway()
        assert validated.execute is not None
        result = await gateway.execute(caller_scope=scope, request=validated.execute.request)
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    if validated.operation == "cancel":
        gateway = _gateway()
        assert validated.request_id is not None
        result = await gateway.stop(
            caller_scope=scope,
            request_id=validated.request_id,
            reason=validated.reason,
        )
        return json.dumps(_stop_result(result), ensure_ascii=False)
    return json.dumps(
        await _read_progress(validated, caller_scope=scope),
        ensure_ascii=False,
    )


async def _read_progress(
    validated: MinecraftOperateToolInput, *, caller_scope: str
) -> dict[str, Any]:
    if _control_plane is not None:
        return await _read_gateway_progress(
            _control_plane.gateway, validated, caller_scope=caller_scope
        )
    bridge = _require_bridge()
    journal = SQLiteCommandJournal(
        bridge.config.journal_path,
        queue_capacity=bridge.config.queue_capacity,
    )
    await journal.connect()
    mission_repository: SQLiteMissionRepository | None = None
    try:
        if validated.projection_kind == "missions":
            mission_repository = SQLiteMissionRepository(bridge.config.journal_path)
            await mission_repository.connect()
            page = await MissionProjectionService(
                repository=mission_repository,
                journal=journal,
            ).read(
                caller_scope=caller_scope,
                limit=validated.limit,
                cursor=validated.cursor,
            )
            return page.model_dump(mode="json")
        if validated.command_id:
            result = await journal.get_command(validated.command_id)
            if result is None or result.caller_scope != caller_scope:
                raise KeyError("COMMAND_NOT_FOUND")
        elif validated.request_id:
            result = await journal.find_by_request(caller_scope, validated.request_id)
            if result is None:
                raise KeyError("COMMAND_NOT_FOUND")
        else:
            result = await journal.read_projection(
                caller_scope, limit=validated.limit, cursor=validated.cursor
            )
        return result.model_dump(mode="json")
    finally:
        if mission_repository is not None:
            await mission_repository.close()
        await journal.close()


async def _read_gateway_progress(
    gateway: Any,
    validated: MinecraftOperateToolInput,
    *,
    caller_scope: str,
) -> dict[str, Any]:
    if validated.projection_kind == "missions":
        page = await gateway.status_missions(
            caller_scope=caller_scope, limit=validated.limit, cursor=validated.cursor
        )
        return page.model_dump(mode="json")
    if validated.command_id:
        result = await gateway.status_command(
            caller_scope=caller_scope, command_id=validated.command_id
        )
    elif validated.request_id:
        result = await gateway.status_request(
            caller_scope=caller_scope, request_id=validated.request_id
        )
    else:
        result = await gateway.status(
            caller_scope=caller_scope, limit=validated.limit, cursor=validated.cursor
        )
    return result.model_dump(mode="json")


def get_minecraft_tools() -> list[Any]:
    """Return the exact two public Minecraft robot capabilities."""

    return [mc_connection, mc_operate_bot]


async def read_minecraft_command_activity(command_id: str) -> dict[str, Any] | None:
    """Read one command and its journal transitions without opening a new writer."""

    if _control_plane is None:
        return None
    command = await _control_plane.repository.get_command(command_id)
    if command is None:
        return None
    transitions = await _control_plane.repository.transitions(command_id)
    return {
        "command_id": command.command_id,
        "request_id": command.request_id,
        "state": command.state.value,
        "failure_reason": command.blocked_reason_code,
        "transitions": [item.model_dump(mode="json") for item in transitions],
    }


def _require_bridge() -> MinecraftMcpBridge:
    if _bridge is None:
        raise RuntimeError("Minecraft MCP client is not configured")
    return _bridge


def _gateway():
    if _control_plane is None:
        raise RuntimeError("Minecraft bot is not connected; call mc_connection connect first")
    return _control_plane.gateway


async def _stop_control_plane(*, request_id: str, reason: str) -> None:
    if _control_plane is None:
        return
    await _control_plane.gateway.stop(
        caller_scope=_caller_scope.get(),
        request_id=f"{request_id}:cancel",
        reason=reason,
    )


async def _close_control_plane() -> None:
    global _control_plane
    if _control_plane is not None:
        await _control_plane.close()
        _control_plane = None


def _stop_result(result: Any) -> dict[str, Any]:
    return {
        "stop_command_id": result.stop_command_id,
        "idempotency_reused": result.idempotency_reused,
        "active_command_id": result.active_command_id,
        "cancelled_command_ids": result.cancelled_command_ids,
        "recovery_error": result.recovery_error,
    }
