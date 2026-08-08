"""Read-only region and vanilla advancement evidence contracts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from ._base import V2ContractModel
from .observations import WorldIdentitySnapshot
from .requests import RegionBounds


class RegionInspection(V2ContractModel):
    schema_version: Literal["2"] = "2"
    inspection_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    world_identity: WorldIdentitySnapshot
    captured_at_ms: int = Field(ge=0)
    tick: int = Field(ge=0)
    observation_id: str = Field(min_length=1, max_length=128)
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bounds: RegionBounds
    blocks: dict[str, str] = Field(default_factory=dict, max_length=4096)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _positions_are_inside_bounds(self) -> Self:
        if self.runtime_instance_id != self.world_identity.runtime_instance_id:
            raise ValueError("inspection world identity does not match runtime")
        if len(self.blocks) > self.bounds.volume:
            raise ValueError("inspection contains more blocks than region volume")
        for key in self.blocks:
            try:
                x, y, z = (int(value) for value in key.split(","))
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid inspected block coordinate") from exc
            if not (
                self.bounds.min.x <= x <= self.bounds.max.x
                and self.bounds.min.y <= y <= self.bounds.max.y
                and self.bounds.min.z <= z <= self.bounds.max.z
            ):
                raise ValueError("block position is outside inspected region")
        return self


class AdvancementObservedEvent(V2ContractModel):
    schema_version: Literal["2"] = "2"
    event_id: str = Field(min_length=1, max_length=128)
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    world_identity: WorldIdentitySnapshot
    advancement_id: str = Field(min_length=1, max_length=256)
    action: Literal["add", "remove"]
    observation_id: str = Field(min_length=1, max_length=128)
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at_ms: int = Field(ge=0)
    tick: int = Field(ge=0)
    source: Literal["version_adapter"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _world_matches_runtime(self) -> Self:
        if self.runtime_instance_id != self.world_identity.runtime_instance_id:
            raise ValueError("advancement world identity does not match runtime")
        return self
