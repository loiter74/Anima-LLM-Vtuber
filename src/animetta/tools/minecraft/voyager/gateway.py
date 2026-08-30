"""Typed asynchronous admission and projection facade for the three public tools."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate as validate_json
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from animetta.tools.gamebot.contracts.v2 import RuntimeManifest, canonical_json_hash
from animetta.tools.minecraft.mission.coordinator import MissionCoordinator
from animetta.tools.minecraft.mission.events import ProjectionEventPublisher
from animetta.tools.minecraft.mission.models import MissionSpec
from animetta.tools.minecraft.mission.projection import (
    MissionProjectionPage,
    MissionProjectionService,
)

from .budget import ModeBudgetPolicy, RequestedBudget, effective_budget
from .command_models import TERMINAL_COMMAND_STATES
from .goal_models import AtomicAction
from .journal import CommandDraft, CommandJournal, JournalCommand, ProjectionPage
from .public_activity import PublicActivityPage, project_activity_page
from .stop import GlobalStopBarrier, StopResult


class ExecuteMissionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["2"] = "2"
    kind: Literal["mission"] = "mission"
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:\-]{1,128}$")
    mission: MissionSpec
    requested_budget: RequestedBudget | None = None
    wait_seconds: float = Field(default=0, ge=0)


class ExecuteAtomicRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["2"] = "2"
    kind: Literal["atomic"] = "atomic"
    request_id: str = Field(pattern=r"^[A-Za-z0-9_.:\-]{1,128}$")
    action: AtomicAction
    requested_budget: RequestedBudget = RequestedBudget()
    wait_seconds: float = Field(default=0, ge=0)


ExecuteRequest = Annotated[
    ExecuteMissionRequest | ExecuteAtomicRequest,
    Field(discriminator="kind"),
]
EXECUTE_REQUEST_ADAPTER: TypeAdapter[ExecuteRequest] = TypeAdapter(ExecuteRequest)


class CommandHandle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    command_id: str
    request_id: str
    queue_sequence: int
    state: str
    accepted_at_ms: int
    idempotency_reused: bool
    projection_version: int
    terminal_result: dict | None = None


class MissionHandle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    mission_id: str
    request_id: str
    state: str
    accepted_at_ms: int
    idempotency_reused: bool
    projection_version: int
    eligible_objective_id: str | None = None
    eligible_command_id: str | None = None


class VoyagerGateway:
    def __init__(
        self,
        *,
        repository: CommandJournal,
        stop_barrier: GlobalStopBarrier,
        manifest: RuntimeManifest,
        budget_policy: ModeBudgetPolicy,
        now_ms: Callable[[], int],
        make_id: Callable[[str], str],
        max_wait_seconds: float = 10,
        on_command_changed: Callable[[str], Awaitable[None]] | None = None,
        execution_admitted: Callable[[], bool] | None = None,
        mission_coordinator: MissionCoordinator | None = None,
        mission_projection: MissionProjectionService | None = None,
        mission_events: ProjectionEventPublisher | None = None,
        activity_enabled: bool = False,
        max_activity_replay: int = 64,
    ) -> None:
        self._repository = repository
        self._stop_barrier = stop_barrier
        self._manifest = manifest
        self._budget_policy = budget_policy
        self._now_ms = now_ms
        self._make_id = make_id
        self._max_wait_seconds = max_wait_seconds
        self._on_command_changed = on_command_changed
        self._execution_admitted = execution_admitted or (lambda: True)
        self._mission_coordinator = mission_coordinator
        self._mission_projection = mission_projection
        self._mission_events = mission_events
        self._activity_enabled = activity_enabled
        self._max_activity_replay = max_activity_replay

    def bind_missions(
        self,
        *,
        coordinator: MissionCoordinator,
        projection: MissionProjectionService,
    ) -> None:
        """Bind the additive mission control plane during production assembly."""

        self._mission_coordinator = coordinator
        self._mission_projection = projection

    async def _notify(self, command_id: str) -> None:
        if self._on_command_changed is None:
            return
        with contextlib.suppress(Exception):
            await self._on_command_changed(command_id)

    def _validate_atomic(self, action: AtomicAction) -> None:
        try:
            capability = self._manifest.capability(action.capability)
        except KeyError as exc:
            raise ValueError(f"CAPABILITY_NOT_AUTHORIZED: {action.capability}") from exc
        try:
            validate_json(action.parameters, capability.parameters_schema)
        except JSONSchemaValidationError as exc:
            raise ValueError(f"INVALID_CAPABILITY_PARAMETERS: {exc.message}") from exc

    async def execute(
        self,
        *,
        caller_scope: str,
        request: ExecuteRequest,
    ) -> CommandHandle | MissionHandle:
        if not self._execution_admitted():
            raise RuntimeError("CONTROLLER_QUARANTINED")
        if isinstance(request, ExecuteMissionRequest):
            return await self._execute_mission(caller_scope=caller_scope, request=request)

        self._validate_atomic(request.action)
        maximum = self._budget_policy.maximum_for("atomic")
        effective = effective_budget(request.requested_budget, maximum)
        canonical_payload = {
            "contract_version": request.contract_version,
            "kind": request.kind,
            "action": request.action.model_dump(mode="json"),
            "requested_budget": request.requested_budget.model_dump(mode="json", exclude_none=True),
        }
        request_hash = canonical_json_hash(canonical_payload)
        now = self._now_ms()
        draft = CommandDraft(
            command_id=self._make_id("command"),
            caller_scope=caller_scope,
            request_id=request.request_id,
            request_hash=request_hash,
            kind="execute",
            mode="atomic",
            payload=canonical_payload,
            requested_budget=request.requested_budget.model_dump(mode="json", exclude_none=True),
            effective_budget=effective.model_dump(mode="json"),
            accepted_at_ms=now,
            queue_deadline_ms=now + effective.queue_timeout_ms,
            execution_deadline_ms=(
                now + effective.queue_timeout_ms + effective.execution_timeout_ms
            ),
        )
        command, reused = await self._repository.create_command(draft)
        await self._notify(command.command_id)
        wait_seconds = min(request.wait_seconds, self._max_wait_seconds)
        if wait_seconds > 0:
            deadline = asyncio.get_running_loop().time() + wait_seconds
            while asyncio.get_running_loop().time() < deadline:
                current = await self._repository.get_command(command.command_id)
                if current is not None and current.state in TERMINAL_COMMAND_STATES:
                    command = current
                    break
                await asyncio.sleep(min(0.01, wait_seconds))
        projection_version = int(getattr(self._repository, "projection_version", 0))
        return CommandHandle(
            command_id=command.command_id,
            request_id=command.request_id,
            queue_sequence=command.queue_sequence,
            state=command.state.value,
            accepted_at_ms=command.accepted_at_ms,
            idempotency_reused=reused,
            projection_version=projection_version,
            terminal_result=command.terminal_result,
        )

    async def _execute_mission(
        self,
        *,
        caller_scope: str,
        request: ExecuteMissionRequest,
    ) -> MissionHandle:
        if self._mission_coordinator is None or self._mission_projection is None:
            raise RuntimeError("MISSION_CONTROL_PLANE_NOT_READY")
        mission = self._authorized_mission(request)
        advance = await self._mission_coordinator.submit(
            caller_scope=caller_scope,
            request_id=request.request_id,
            spec=mission,
            occurred_at_ms=self._now_ms(),
        )
        page = await self._mission_projection.read(caller_scope=caller_scope, limit=100)
        projection = next(item for item in page.missions if item.mission_id == mission.mission_id)
        if self._mission_events is not None:
            with contextlib.suppress(Exception):
                await self._mission_events.publish_mission(projection)
        return MissionHandle(
            mission_id=advance.mission_id,
            request_id=request.request_id,
            state=advance.mission_status.value,
            accepted_at_ms=projection.updated_at_ms,
            idempotency_reused=advance.idempotency_reused,
            projection_version=projection.projection_version,
            eligible_objective_id=advance.eligible_objective_id,
            eligible_command_id=advance.eligible_command_id,
        )

    def _authorized_mission(self, request: ExecuteMissionRequest) -> MissionSpec:
        maxima = tuple(
            self._budget_policy.maximum_for(mode) for mode in ("learn", "live", "fallback")
        )
        configured_resource_maxima = {
            resource: max(item.resource_consumption.get(resource, 0) for item in maxima)
            for resource in {key for item in maxima for key in item.resource_consumption}
        }
        mission_resources = request.mission.budget.resource_consumption
        maximum = type(maxima[0])(
            queue_timeout_ms=max(item.queue_timeout_ms for item in maxima),
            execution_timeout_ms=max(item.execution_timeout_ms for item in maxima),
            max_actions=max(item.max_actions for item in maxima),
            max_strategy_attempts=max(item.max_strategy_attempts for item in maxima),
            max_travel_distance=max(item.max_travel_distance for item in maxima),
            max_blocks_changed=max(item.max_blocks_changed for item in maxima),
            max_damage_taken=max(item.max_damage_taken for item in maxima),
            protected_items=frozenset().union(*(item.protected_items for item in maxima)),
            # Minecraft's item namespace is open-ended. A mode ceiling only narrows
            # resource names it explicitly configures; every other name remains
            # bounded by the already finite, validated mission declaration.
            resource_consumption={
                resource: min(amount, configured_resource_maxima.get(resource, amount))
                for resource, amount in mission_resources.items()
            },
        )
        mission_request = RequestedBudget.model_validate(
            request.mission.budget.model_dump(mode="python")
        )
        authorized = effective_budget(mission_request, maximum)
        if request.requested_budget is not None:
            authorized = effective_budget(request.requested_budget, authorized)
        payload = request.mission.model_dump(mode="json")
        payload["budget"] = authorized.model_dump(mode="json")
        return MissionSpec.model_validate(payload)

    async def status(
        self,
        *,
        caller_scope: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ProjectionPage:
        return await self._repository.read_projection(  # type: ignore[attr-defined]
            caller_scope, limit=limit, cursor=cursor
        )

    async def status_command(self, *, caller_scope: str, command_id: str) -> JournalCommand:
        command = await self._repository.get_command(command_id)
        if command is None or command.caller_scope != caller_scope:
            raise KeyError("COMMAND_NOT_FOUND")
        return command

    async def status_request(self, *, caller_scope: str, request_id: str) -> JournalCommand:
        command = await self._repository.find_by_request(  # type: ignore[attr-defined]
            caller_scope, request_id
        )
        if command is None:
            raise KeyError("COMMAND_NOT_FOUND")
        return command

    async def status_missions(
        self,
        *,
        caller_scope: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> MissionProjectionPage:
        if self._mission_projection is None:
            raise RuntimeError("MISSION_CONTROL_PLANE_NOT_READY")
        return await self._mission_projection.read(
            caller_scope=caller_scope,
            limit=limit,
            cursor=cursor,
        )

    async def status_activities(
        self,
        *,
        caller_scope: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> PublicActivityPage:
        if not self._activity_enabled:
            return PublicActivityPage(events=())
        if limit < 1:
            raise ValueError("limit must be positive")
        page = await self._repository.read_activity(
            caller_scope,
            limit=min(limit, self._max_activity_replay, 100),
            cursor=cursor,
        )
        return project_activity_page(page)

    async def replay_public_activities(self, *, limit: int = 20) -> PublicActivityPage:
        """Return the latest global public stream for trusted server-side replay."""

        if not self._activity_enabled:
            return PublicActivityPage(events=())
        if limit < 1:
            raise ValueError("limit must be positive")
        page = await self._repository.read_recent_activity(
            limit=min(limit, self._max_activity_replay, 100)
        )
        return project_activity_page(page)

    async def stop(self, *, caller_scope: str, request_id: str, reason: str) -> StopResult:
        result = await self._stop_barrier.stop(
            caller_scope=caller_scope, request_id=request_id, reason=reason
        )
        for command_id in (
            result.stop_command_id,
            *result.cancelled_command_ids,
            *(() if result.active_command_id is None else (result.active_command_id,)),
        ):
            await self._notify(command_id)
        return result
