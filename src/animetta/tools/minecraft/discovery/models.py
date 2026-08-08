"""Typed evidence and projections for world-scoped discoveries."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash

FactKind = Literal["item", "block", "entity", "biome", "structure", "recipe", "advancement"]


class WorldFactState(StrEnum):
    OBSERVED = "observed"
    ACQUIRED = "acquired"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class WorldFactIdentity(_FrozenModel):
    world_identity_hash: str = Field(pattern=r"^[0-9a-z]{64}$")
    environment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_kind: FactKind
    fact_key: str = Field(min_length=1, max_length=256)

    @property
    def fact_id(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


class ObservedFact(_FrozenModel):
    fact_kind: FactKind
    fact_key: str = Field(min_length=1, max_length=256)
    coarse_location: str | None = Field(default=None, max_length=256)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryObservation(_FrozenModel):
    runtime_instance_id: str = Field(min_length=1, max_length=256)
    world_identity_hash: str = Field(pattern=r"^[0-9a-z]{64}$")
    environment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_id: str = Field(min_length=1, max_length=256)
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at_ms: int = Field(ge=0)
    tick: int = Field(ge=0)
    facts: tuple[ObservedFact, ...]


class AcquisitionEvidence(_FrozenModel):
    fact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_instance_id: str = Field(min_length=1, max_length=256)
    world_identity_hash: str = Field(pattern=r"^[0-9a-z]{64}$")
    environment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    command_id: str = Field(min_length=1, max_length=256)
    receipt_id: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=256)
    before_observation_id: str = Field(min_length=1, max_length=256)
    after_observation_id: str = Field(min_length=1, max_length=256)
    inventory_delta: int
    committed: bool
    fallback_only: bool
    explained_inventory_delta: bool
    observed_at_ms: int = Field(ge=0)


class WorldFact(_FrozenModel):
    fact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_instance_id: str = Field(min_length=1, max_length=256)
    identity: WorldFactIdentity
    state: WorldFactState
    first_observation_ref: str
    first_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_observation_ref: str
    last_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    first_seen_at_ms: int = Field(ge=0)
    last_seen_at_ms: int = Field(ge=0)
    first_seen_tick: int = Field(ge=0)
    last_seen_tick: int = Field(ge=0)
    observation_count: int = Field(gt=0)
    coarse_location: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    acquisition_command_ref: str | None = None
    acquisition_receipt_ref: str | None = None
    acquisition_observation_ref: str | None = None


class DiscoveryProjectionResult(_FrozenModel):
    new_facts: tuple[WorldFact, ...] = ()
    updated_facts: tuple[WorldFact, ...] = ()
