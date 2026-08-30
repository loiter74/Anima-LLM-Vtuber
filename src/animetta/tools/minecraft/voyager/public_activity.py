"""Durable, public-safe Minecraft activity projections for livestream consumers."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, cast

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

if TYPE_CHECKING:
    from .journal import JournalCommand

PublicActivityPhase = Literal[
    "planning",
    "observing",
    "committed",
    "acting",
    "checking",
    "recovering",
    "finished",
]
PublicActivityIntent = Literal[
    "acquire",
    "craft",
    "build",
    "travel",
    "combat",
    "survive",
    "learn",
    "discover",
    "interact",
]
PublicActivityOutcome = Literal["active", "succeeded", "failed", "cancelled", "blocked"]
RuntimeActionPhase = Literal[
    "accepted",
    "assessing",
    "locating",
    "moving",
    "aiming",
    "acting",
    "waiting",
    "verifying",
    "recovering",
    "completed",
    "failed",
    "cancelled",
]

_PUBLIC_INTENTS = frozenset(
    {
        "acquire",
        "craft",
        "build",
        "travel",
        "combat",
        "survive",
        "learn",
        "discover",
        "interact",
    }
)
_FOCUS_KIND_BY_INTENT: dict[str, Literal["item", "entity", "place", "structure", "condition"]] = {
    "acquire": "item",
    "craft": "item",
    "build": "structure",
    "travel": "place",
    "combat": "entity",
    "survive": "condition",
    "learn": "condition",
    "discover": "condition",
    "interact": "condition",
}
_INTENT_BY_CAPABILITY = {
    "collect": "acquire",
    "craft": "craft",
    "smelt": "craft",
    "place": "build",
    "goto": "travel",
    "move": "travel",
    "attack": "combat",
    "inspect": "discover",
    "observe": "discover",
}
_UNSAFE_LABEL = re.compile(r"(?i)(?:\bBearer\s+|\bsk-[A-Za-z0-9_-]{6,}|[\r\n\x00-\x1f])")
_PUBLIC_FOCUS_LABELS = {
    "minecraft:birch_planks": "birch planks",
    "minecraft:cobblestone": "cobblestone",
    "minecraft:cooked_beef": "cooked beef",
    "minecraft:copper_ingot": "copper ingot",
    "minecraft:copper_ore": "copper ore",
    "minecraft:crafting_table": "crafting table",
    "minecraft:creeper": "creeper",
    "minecraft:diamond_block": "diamond block",
    "minecraft:diamond_pickaxe": "diamond pickaxe",
    "minecraft:oak_door": "oak door",
    "minecraft:oak_log": "oak log",
    "minecraft:oak_planks": "oak planks",
    "minecraft:raw_copper": "raw copper",
    "minecraft:skeleton": "skeleton",
    "minecraft:spruce_planks": "spruce planks",
    "minecraft:starter_shelter": "starter shelter",
    "minecraft:stone_pickaxe": "stone pickaxe",
    "minecraft:stone_sword": "stone sword",
    "minecraft:white_bed": "white bed",
    "minecraft:zombie": "zombie",
}
_RUNTIME_PHASE_TO_PUBLIC: dict[RuntimeActionPhase, PublicActivityPhase | None] = {
    "accepted": None,
    "assessing": "observing",
    "locating": "observing",
    "moving": "acting",
    "aiming": "acting",
    "acting": "acting",
    "waiting": "acting",
    "verifying": "checking",
    "recovering": "recovering",
    "completed": None,
    "failed": None,
    "cancelled": None,
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PublicActivityFocus(_FrozenModel):
    kind: Literal["item", "entity", "place", "structure", "condition"]
    label: str = Field(min_length=1, max_length=64)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        normalized = value.strip()
        if _UNSAFE_LABEL.search(normalized) or normalized.startswith(("/", "\\")):
            raise ValueError("unsafe public activity focus label")
        return normalized


class PublicActivityProgress(_FrozenModel):
    current: int = Field(ge=0)
    total: int = Field(gt=0)
    unit: Literal["objectives", "items", "blocks", "actions"]

    @model_validator(mode="after")
    def current_does_not_exceed_total(self) -> Self:
        if self.current > self.total:
            raise ValueError("activity progress current exceeds total")
        return self


class PublicActivityPayload(_FrozenModel):
    phase: PublicActivityPhase
    intent: PublicActivityIntent | None = None
    focus: PublicActivityFocus | None = None
    progress: PublicActivityProgress | None = None
    outcome: PublicActivityOutcome = "active"

    @model_validator(mode="after")
    def terminal_outcome_matches_phase(self) -> Self:
        terminal = self.outcome != "active"
        if terminal != (self.phase == "finished"):
            raise ValueError("only finished activity may carry a terminal outcome")
        return self


class ActivityDraft(_FrozenModel):
    """Internal persistence envelope; never serialize this model to public callers."""

    source_key: str = Field(min_length=1, max_length=512)
    command_id: str = Field(min_length=1, max_length=256)
    caller_scope: str = Field(min_length=1, max_length=256)
    mission_id: str | None = Field(default=None, max_length=128)
    payload: PublicActivityPayload
    occurred_at_ms: int = Field(ge=0)


class ActivityRecord(ActivityDraft):
    sequence: int = Field(gt=0)

    def matches(self, draft: ActivityDraft) -> bool:
        """Return whether ``draft`` is an idempotent replay of this record."""

        return (
            self.source_key == draft.source_key
            and self.command_id == draft.command_id
            and self.caller_scope == draft.caller_scope
            and self.mission_id == draft.mission_id
            and self.payload == draft.payload
        )


class ActivityRecordPage(_FrozenModel):
    records: tuple[ActivityRecord, ...]
    next_cursor: str | None = None


class MinecraftActivityProjection(_FrozenModel):
    schema_version: Literal["1"] = "1"
    event: Literal["minecraft.activity.projection"] = "minecraft.activity.projection"
    event_id: str = Field(min_length=1, max_length=128)
    projection_kind: Literal["activity"] = "activity"
    projection_version: int = Field(gt=0)
    occurred_at_ms: int = Field(ge=0)
    mission_id: str | None = Field(default=None, max_length=128)
    entity_id: str = Field(min_length=1, max_length=128)
    payload: PublicActivityPayload


class PublicActivityPage(_FrozenModel):
    events: tuple[MinecraftActivityProjection, ...]
    next_cursor: str | None = None


class RuntimeActionPhaseEvent(_FrozenModel):
    """Strict private bridge envelope; optional runtime detail is discarded before parsing."""

    type: Literal["action_phase"]
    schema_version: Literal["1"]
    runtime_instance_id: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    command_id: str = Field(min_length=1, max_length=256)
    step_id: str = Field(min_length=1, max_length=256)
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    phase_sequence: int = Field(ge=1, le=32)
    phase: RuntimeActionPhase
    occurred_at_ms: int = Field(ge=0)
    presentation_mode: Literal["off", "visual_only", "full"]


class PublicActivityRepository(Protocol):
    async def append_activity(
        self,
        draft: ActivityDraft,
        *,
        retention_before_ms: int | None = None,
    ) -> tuple[ActivityRecord, bool]: ...

    async def read_activity(
        self,
        caller_scope: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ActivityRecordPage: ...

    async def read_recent_activity(self, *, limit: int = 20) -> ActivityRecordPage: ...

    async def expire_activity(self, *, before_ms: int) -> int: ...

    async def get_command(self, command_id: str) -> JournalCommand | None: ...


def project_activity(record: ActivityRecord) -> MinecraftActivityProjection:
    return MinecraftActivityProjection(
        event_id=f"activity:{record.sequence}",
        projection_version=record.sequence,
        occurred_at_ms=record.occurred_at_ms,
        mission_id=record.mission_id,
        entity_id="minecraft",
        payload=record.payload,
    )


def project_activity_page(page: ActivityRecordPage) -> PublicActivityPage:
    return PublicActivityPage(
        events=tuple(project_activity(record) for record in page.records),
        next_cursor=page.next_cursor,
    )


class PublicActivityEventPublisher:
    """Best-effort publisher with process-local duplicate suppression."""

    def __init__(
        self,
        *,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        maximum_delivered_ids: int = 10_000,
    ) -> None:
        self._emit = emit
        self._maximum_delivered_ids = maximum_delivered_ids
        self._delivered: dict[str, None] = {}

    async def publish(self, record: ActivityRecord) -> bool:
        event = project_activity(record)
        if event.event_id in self._delivered:
            return False
        await self._emit(event.model_dump(mode="json"))
        self._delivered[event.event_id] = None
        while len(self._delivered) > self._maximum_delivered_ids:
            self._delivered.pop(next(iter(self._delivered)))
        return True


class PublicActivityRecorder:
    """Sanitize, commit, then publish public activity without affecting gameplay."""

    def __init__(
        self,
        *,
        repository: PublicActivityRepository,
        enabled: bool,
        now_ms: Callable[[], int],
        publisher: PublicActivityEventPublisher | None = None,
        retention_ms: int | None = None,
    ) -> None:
        if retention_ms is not None and retention_ms < 1:
            raise ValueError("activity retention must be positive")
        self._repository = repository
        self._enabled = enabled
        self._now_ms = now_ms
        self._publisher = publisher
        self._retention_ms = retention_ms

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def record_command(
        self,
        command: JournalCommand,
        *,
        source_key: str,
        phase: PublicActivityPhase,
        outcome: PublicActivityOutcome = "active",
        progress: PublicActivityProgress | None = None,
    ) -> ActivityRecord | None:
        if (
            not self._enabled
            or command.mode == "atomic"
            or not isinstance(command.payload.get("goal"), dict)
        ):
            return None
        try:
            intent, focus = _public_context(command)
            occurred_at_ms = self._now_ms()
            draft = ActivityDraft(
                source_key=source_key,
                command_id=command.command_id,
                caller_scope=command.caller_scope,
                mission_id=_mission_id(command),
                payload=PublicActivityPayload(
                    phase=phase,
                    intent=intent,
                    focus=focus,
                    progress=progress,
                    outcome=outcome,
                ),
                occurred_at_ms=occurred_at_ms,
            )
            record, _reused = await self._repository.append_activity(
                draft,
                retention_before_ms=(
                    occurred_at_ms - self._retention_ms if self._retention_ms is not None else None
                ),
            )
        except Exception as exc:
            logger.warning("Minecraft public activity persistence failed: {}", type(exc).__name__)
            return None
        if self._publisher is not None:
            try:
                await self._publisher.publish(record)
            except Exception as exc:
                logger.warning("Minecraft public activity publish failed: {}", type(exc).__name__)
        return record


class RuntimePublicActivityAggregator:
    """Map validated private runtime phases into the public durable vocabulary."""

    def __init__(
        self,
        *,
        bridge: Any,
        repository: PublicActivityRepository,
        recorder: PublicActivityRecorder,
    ) -> None:
        self._bridge = bridge
        self._repository = repository
        self._recorder = recorder
        self._tasks: set[asyncio.Task[None]] = set()
        self._correlation_tails: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._last_phase_sequence: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._unsubscribe: Callable[[], None] | None = None
        self._closed = False
        self._started = False
        self.invalid_events = 0

    def start(self) -> None:
        if self._started:
            return
        unsubscribe = self._bridge.add_runtime_event_callback(self._on_event)
        self._unsubscribe = unsubscribe if callable(unsubscribe) else None
        self._started = True

    def _on_event(self, payload: dict[str, Any]) -> None:
        if self._closed or payload.get("type") != "action_phase":
            return
        core_payload = {name: payload.get(name) for name in RuntimeActionPhaseEvent.model_fields}
        try:
            event = RuntimeActionPhaseEvent.model_validate(core_payload)
        except ValidationError:
            self.invalid_events += 1
            return
        correlation_key = (event.runtime_instance_id, event.correlation_id)
        previous_sequence = self._last_phase_sequence.get(correlation_key, 0)
        if event.phase_sequence <= previous_sequence:
            return
        self._last_phase_sequence[correlation_key] = event.phase_sequence
        self._last_phase_sequence.move_to_end(correlation_key)
        while len(self._last_phase_sequence) > 2_048:
            self._last_phase_sequence.popitem(last=False)
        public_phase = _RUNTIME_PHASE_TO_PUBLIC[event.phase]
        if public_phase is None:
            return
        previous = self._correlation_tails.get(correlation_key)
        task = asyncio.get_running_loop().create_task(
            self._record_after(previous, event, public_phase),
            name="minecraft-public-activity-phase",
        )
        self._correlation_tails[correlation_key] = task
        self._tasks.add(task)
        task.add_done_callback(partial(self._task_done, correlation_key))

    def _task_done(
        self,
        correlation_key: tuple[str, str],
        task: asyncio.Task[None],
    ) -> None:
        self._tasks.discard(task)
        if self._correlation_tails.get(correlation_key) is task:
            self._correlation_tails.pop(correlation_key, None)

    async def _record_after(
        self,
        previous: asyncio.Task[None] | None,
        event: RuntimeActionPhaseEvent,
        public_phase: PublicActivityPhase,
    ) -> None:
        if previous is not None:
            await previous
        await self._record(event, public_phase)

    async def _record(
        self,
        event: RuntimeActionPhaseEvent,
        public_phase: PublicActivityPhase,
    ) -> None:
        try:
            command = await self._repository.get_command(event.command_id)
            if command is None:
                return
            source_digest = hashlib.sha256(
                (
                    f"{event.runtime_instance_id}\0{event.correlation_id}\0{event.phase_sequence}"
                ).encode()
            ).hexdigest()
            await self._recorder.record_command(
                command,
                source_key=f"runtime-phase:{source_digest}",
                phase=public_phase,
            )
        except Exception as exc:
            logger.warning("Minecraft runtime activity aggregation failed: {}", type(exc).__name__)

    async def drain(self) -> None:
        self._closed = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))
        self._correlation_tails.clear()
        self._last_phase_sequence.clear()


def _mission_id(command: JournalCommand) -> str | None:
    value = command.payload.get("mission_id")
    return value if isinstance(value, str) and value else None


def _public_context(
    command: JournalCommand,
) -> tuple[PublicActivityIntent, PublicActivityFocus | None]:
    goal = command.payload.get("goal")
    intent_value: object = None
    target: object = None
    if isinstance(goal, dict):
        intent_value = goal.get("intent")
        target = goal.get("target")
    elif isinstance(command.payload.get("action"), dict):
        action = command.payload["action"]
        intent_value = _INTENT_BY_CAPABILITY.get(str(action.get("capability")), "interact")

    intent_text = (
        intent_value
        if isinstance(intent_value, str) and intent_value in _PUBLIC_INTENTS
        else "interact"
    )
    intent = cast(PublicActivityIntent, intent_text)
    focus = _public_focus(intent_text, target)
    return intent, focus


def _public_focus(intent: str, target: object) -> PublicActivityFocus | None:
    if not isinstance(target, str):
        return None
    label = _PUBLIC_FOCUS_LABELS.get(target)
    if label is None:
        return None
    try:
        return PublicActivityFocus(
            kind=_FOCUS_KIND_BY_INTENT.get(intent, "condition"),
            label=label,
        )
    except ValueError:
        return None


__all__ = [
    "ActivityDraft",
    "ActivityRecord",
    "ActivityRecordPage",
    "MinecraftActivityProjection",
    "PublicActivityEventPublisher",
    "PublicActivityFocus",
    "PublicActivityOutcome",
    "PublicActivityPage",
    "PublicActivityPayload",
    "PublicActivityProgress",
    "PublicActivityRecorder",
    "RuntimeActionPhaseEvent",
    "RuntimePublicActivityAggregator",
    "project_activity",
    "project_activity_page",
]
