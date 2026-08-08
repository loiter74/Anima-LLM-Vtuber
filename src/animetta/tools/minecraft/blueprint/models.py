"""Bounded declarative structure blueprints and compiled place plans."""

from __future__ import annotations

from collections import Counter
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from animetta.tools.gamebot.contracts.v2 import RegionBounds, canonical_json_hash
from animetta.tools.minecraft.voyager.budget import BudgetUsage

BlockPosition = tuple[int, int, int]


def _resource_id(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("block identity cannot be empty")
    return normalized if ":" in normalized else f"minecraft:{normalized}"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BlueprintDimensions(_FrozenModel):
    width: int = Field(gt=0, le=16)
    height: int = Field(gt=0, le=16)
    depth: int = Field(gt=0, le=16)

    @property
    def volume(self) -> int:
        return self.width * self.height * self.depth


class PaletteEntry(_FrozenModel):
    default_block: str
    allowed_blocks: tuple[str, ...] = Field(min_length=1, max_length=64)

    @field_validator("default_block")
    @classmethod
    def _normal_default(cls, value: str) -> str:
        return _resource_id(value)

    @field_validator("allowed_blocks")
    @classmethod
    def _normal_allowed(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_resource_id(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate allowed block")
        return normalized

    @model_validator(mode="after")
    def _default_is_approved(self) -> Self:
        if self.default_block not in self.allowed_blocks:
            raise ValueError("default block must be approved")
        return self


class RelativePlacement(_FrozenModel):
    x: int = Field(ge=0, le=15)
    y: int = Field(ge=0, le=15)
    z: int = Field(ge=0, le=15)
    material: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    role: str = Field(default="structure", min_length=1, max_length=64)
    action_required: bool = True
    action_source: BlockPosition | None = None

    @property
    def position(self) -> BlockPosition:
        return (self.x, self.y, self.z)

    @model_validator(mode="after")
    def _derived_placement_has_source(self) -> Self:
        if self.action_required == (self.action_source is not None):
            raise ValueError("only derived placements require an action source")
        return self


class SemanticFeature(_FrozenModel):
    feature_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    kind: Literal["door", "roof", "light", "bed", "enclosure"]
    positions: tuple[BlockPosition, ...] = Field(min_length=1, max_length=4096)


class BlueprintVerificationRules(_FrozenModel):
    exact_placements: Literal[True] = True
    required_feature_ids: frozenset[str] = frozenset()
    required_air: tuple[BlockPosition, ...] = Field(default=(), max_length=4096)


class StructureBlueprint(_FrozenModel):
    schema_version: Literal["1"] = "1"
    blueprint_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,127}$")
    dimensions: BlueprintDimensions
    palette: dict[str, PaletteEntry] = Field(min_length=1, max_length=32)
    placements: tuple[RelativePlacement, ...] = Field(min_length=1, max_length=4096)
    semantic_features: tuple[SemanticFeature, ...] = Field(default=(), max_length=64)
    verification: BlueprintVerificationRules = BlueprintVerificationRules()

    @property
    def volume(self) -> int:
        return self.dimensions.volume

    @property
    def canonical_hash(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def _bounded_and_referentially_valid(self) -> Self:
        if self.volume > 4096:
            raise ValueError("blueprint volume exceeds 4096 blocks")
        positions = [placement.position for placement in self.placements]
        if len(positions) != len(set(positions)):
            raise ValueError("duplicate relative placement")
        unknown_materials = {placement.material for placement in self.placements} - set(
            self.palette
        )
        if unknown_materials:
            raise ValueError(f"unknown palette material: {sorted(unknown_materials)!r}")

        def inside(position: BlockPosition) -> bool:
            x, y, z = position
            return (
                0 <= x < self.dimensions.width
                and 0 <= y < self.dimensions.height
                and 0 <= z < self.dimensions.depth
            )

        if any(not inside(position) for position in positions):
            raise ValueError("placement is outside blueprint dimensions")
        by_position = {placement.position: placement for placement in self.placements}
        for placement in self.placements:
            if placement.action_source is None:
                continue
            source = by_position.get(placement.action_source)
            if source is None or not source.action_required:
                raise ValueError("derived placement action source is not executable")
            if source.material != placement.material:
                raise ValueError("derived placement must share its source material")
        feature_ids = [feature.feature_id for feature in self.semantic_features]
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("duplicate semantic feature ID")
        if any(
            not inside(position)
            for feature in self.semantic_features
            for position in feature.positions
        ):
            raise ValueError("semantic feature is outside blueprint dimensions")
        if any(not inside(position) for position in self.verification.required_air):
            raise ValueError("required air is outside blueprint dimensions")
        unknown_features = self.verification.required_feature_ids - set(feature_ids)
        if unknown_features:
            raise ValueError(f"unknown required feature: {sorted(unknown_features)!r}")
        return self


class BlueprintBinding(_FrozenModel):
    origin: BlockPosition
    materials: dict[str, str] = Field(default_factory=dict, max_length=32)

    @field_validator("materials")
    @classmethod
    def _normal_materials(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: _resource_id(value) for key, value in values.items()}


class CompiledPlacement(_FrozenModel):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,127}$")
    capability: Literal["place"] = "place"
    relative_position: BlockPosition
    absolute_position: BlockPosition
    effect_positions: tuple[BlockPosition, ...] = Field(min_length=1, max_length=16)
    block_id: str
    role: str
    parameters: dict[str, str | int]


class CompiledFeature(_FrozenModel):
    feature_id: str
    kind: Literal["door", "roof", "light", "bed", "enclosure"]
    positions: tuple[BlockPosition, ...]


class CompiledBlueprint(_FrozenModel):
    schema_version: Literal["1"] = "1"
    blueprint_id: str
    blueprint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: BlockPosition
    material_bindings: dict[str, str]
    bounds: RegionBounds
    steps: tuple[CompiledPlacement, ...] = Field(max_length=4096)
    expected_blocks: dict[str, str] = Field(max_length=4096)
    expected_roles: dict[str, str] = Field(max_length=4096)
    required_air: tuple[BlockPosition, ...] = Field(max_length=4096)
    features: tuple[CompiledFeature, ...] = Field(max_length=64)
    required_feature_ids: frozenset[str]
    static_cost: BudgetUsage


class BlueprintVerificationResult(_FrozenModel):
    satisfied: bool
    blueprint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    inspection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched_positions: tuple[BlockPosition, ...] = ()
    missing_positions: tuple[BlockPosition, ...] = ()
    conflicting_positions: tuple[BlockPosition, ...] = ()
    unknown_positions: tuple[BlockPosition, ...] = ()
    feature_results: dict[str, bool] = Field(default_factory=dict)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class BlueprintResumePlan(_FrozenModel):
    blueprint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    steps: tuple[CompiledPlacement, ...] = ()
    blocked_conflicts: tuple[BlockPosition, ...] = ()
    unresolved_missing: tuple[BlockPosition, ...] = ()
    static_cost: BudgetUsage


def resource_cost(steps: tuple[CompiledPlacement, ...]) -> dict[str, int]:
    return dict(Counter(step.block_id for step in steps))
