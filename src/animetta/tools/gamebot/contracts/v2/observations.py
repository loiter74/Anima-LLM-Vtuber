"""Versioned GameBot v2 observations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from ._base import V2ContractModel
from .manifest import EnvironmentProfile


class Position(V2ContractModel):
    x: float
    y: float
    z: float


class WorldIdentitySnapshot(V2ContractModel):
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    server_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    world_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: str = Field(min_length=1, max_length=128)


class DiscoverableBlock(V2ContractModel):
    block_id: str = Field(min_length=1, max_length=256)
    position: Position


class DiscoverableEntity(V2ContractModel):
    entity_id: str = Field(min_length=1, max_length=256)
    entity_type: str = Field(min_length=1, max_length=256)
    position: Position
    health: float | None = Field(default=None, ge=0)


class Observation(V2ContractModel):
    schema_version: Literal["2"] = "2"
    observation_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    captured_at_ms: int = Field(ge=0)
    tick: int = Field(ge=0)
    action_sequence: int = Field(ge=0)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile: EnvironmentProfile
    world_identity: WorldIdentitySnapshot
    position: Position | None = None
    health: float | None = Field(default=None, ge=0)
    food: int | None = Field(default=None, ge=0)
    inventory: dict[str, int] = Field(default_factory=dict)
    equipment: dict[str, str] = Field(default_factory=dict)
    environment: dict[str, object] = Field(default_factory=dict)
    biome: str | None = Field(default=None, max_length=256)
    visible_blocks: tuple[DiscoverableBlock, ...] = Field(default=(), max_length=512)
    visible_entities: tuple[DiscoverableEntity, ...] = Field(default=(), max_length=128)
    active_advancements: tuple[str, ...] = Field(default=(), max_length=512)

    @model_validator(mode="after")
    def _world_identity_matches_profile(self) -> Observation:
        world = self.world_identity
        if (
            world.runtime_instance_id != self.runtime_instance_id
            or world.server_identity_hash != self.profile.server_identity_hash
            or world.world_identity_hash != self.profile.world_identity_hash
            or world.dimension != self.profile.dimension
        ):
            raise ValueError("observation world identity does not match runtime profile")
        return self

    @property
    def captured_at(self) -> datetime:
        return datetime.fromtimestamp(self.captured_at_ms / 1000, tz=UTC)
