"""Normalized typed goals and atomic actions accepted by the Voyager gateway."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @property
    def canonical_hash(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json", exclude_none=True))


class InventoryAtLeast(_FrozenModel):
    kind: Literal["inventory_at_least"]
    item: str = Field(pattern=r"^[a-z0-9_:.\-]+$")
    quantity: int = Field(gt=0)


class LocationReached(_FrozenModel):
    kind: Literal["location_reached"]
    x: float
    y: float
    z: float
    tolerance: float = Field(default=1.5, gt=0)


class HealthAtLeast(_FrozenModel):
    kind: Literal["health_at_least"]
    health: float = Field(ge=0, le=20)


class SurvivedDuration(_FrozenModel):
    kind: Literal["survived_duration"]
    duration_ms: int = Field(gt=0)


class EntityDefeated(_FrozenModel):
    kind: Literal["entity_defeated"]
    entity: str = Field(min_length=1, max_length=128)
    quantity: int = Field(default=1, gt=0)


class BlocksPlaced(_FrozenModel):
    kind: Literal["blocks_placed"]
    block: str = Field(min_length=1, max_length=128)
    quantity: int = Field(gt=0)


class WorldFactObserved(_FrozenModel):
    kind: Literal["world_fact_observed"]
    fact_kind: Literal["item", "entity", "biome", "structure", "recipe", "advancement"]
    fact_key: str = Field(min_length=1, max_length=256)


class WorldFactAcquired(_FrozenModel):
    kind: Literal["world_fact_acquired"]
    fact_kind: Literal["item", "entity", "biome", "structure", "recipe", "advancement"]
    fact_key: str = Field(min_length=1, max_length=256)


class StructureMatchesBlueprint(_FrozenModel):
    kind: Literal["structure_matches_blueprint"]
    blueprint_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    blueprint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class VanillaAdvancementObserved(_FrozenModel):
    kind: Literal["vanilla_advancement_observed"]
    advancement_id: str = Field(min_length=1, max_length=256)
    action: Literal["add"] = "add"


SuccessPredicate = Annotated[
    InventoryAtLeast
    | LocationReached
    | HealthAtLeast
    | SurvivedDuration
    | EntityDefeated
    | BlocksPlaced
    | WorldFactObserved
    | WorldFactAcquired
    | StructureMatchesBlueprint
    | VanillaAdvancementObserved,
    Field(discriminator="kind"),
]


class _GoalBase(_FrozenModel):
    target: str = Field(min_length=1, max_length=256)
    quantity: int = Field(default=1, gt=0, le=4096)
    constraints: dict[str, object] = Field(default_factory=dict)
    success_predicates: tuple[SuccessPredicate, ...] = Field(min_length=1)


class AcquireGoal(_GoalBase):
    intent: Literal["acquire"]


class CraftGoal(_GoalBase):
    intent: Literal["craft"]


class BuildGoal(_GoalBase):
    intent: Literal["build"]


class TravelGoal(_GoalBase):
    intent: Literal["travel"]


class CombatGoal(_GoalBase):
    intent: Literal["combat"]


class SurviveGoal(_GoalBase):
    intent: Literal["survive"]


class LearnGoal(_GoalBase):
    intent: Literal["learn"]


class DiscoverGoal(_GoalBase):
    intent: Literal["discover"]
    discovery_kind: Literal["item", "entity", "biome", "structure", "recipe", "advancement"]


GoalSpec = Annotated[
    AcquireGoal
    | CraftGoal
    | BuildGoal
    | TravelGoal
    | CombatGoal
    | SurviveGoal
    | LearnGoal
    | DiscoverGoal,
    Field(discriminator="intent"),
]


class AtomicAction(_FrozenModel):
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    parameters: dict[str, object] = Field(default_factory=dict)


class ExecutionMode(StrEnum):
    LEARN = "learn"
    LIVE = "live"
    FALLBACK = "fallback"
    ATOMIC = "atomic"


class ExecutePayload(_FrozenModel):
    mode: Literal["learn", "live", "fallback", "atomic"]
    goal: GoalSpec | None = None
    action: AtomicAction | None = None

    @model_validator(mode="after")
    def _mode_matches_payload(self) -> ExecutePayload:
        if self.mode == "atomic":
            if self.action is None or self.goal is not None:
                raise ValueError("atomic mode requires one action and no goal")
        elif self.goal is None or self.action is not None:
            raise ValueError(f"{self.mode} mode requires one structured goal and no action")
        return self
