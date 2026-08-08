"""GameBot v2 action, cancellation, and inspection requests."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ._base import V2ContractModel, canonical_json_hash
from .budget import BudgetVector
from .observations import Position


class ActionRequest(V2ContractModel):
    schema_version: Literal["2"] = "2"
    transport_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    step_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    parameters: dict[str, object]
    remaining_budget: BudgetVector
    deadline_ms: int = Field(gt=0)
    previous_receipt_hash: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")

    @property
    def canonical_parameters_hash(self) -> str:
        return canonical_json_hash(self.parameters)


class ObservationRequest(V2ContractModel):
    schema_version: Literal["2"] = "2"
    transport_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    step_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    deadline_ms: int = Field(gt=0)


class RegionBounds(V2ContractModel):
    min: Position
    max: Position

    @model_validator(mode="after")
    def _ordered_integer_bounds(self) -> RegionBounds:
        coordinates = (
            self.min.x,
            self.min.y,
            self.min.z,
            self.max.x,
            self.max.y,
            self.max.z,
        )
        if any(not float(value).is_integer() for value in coordinates):
            raise ValueError("region bounds require integer block coordinates")
        if any(
            minimum > maximum
            for minimum, maximum in (
                (self.min.x, self.max.x),
                (self.min.y, self.max.y),
                (self.min.z, self.max.z),
            )
        ):
            raise ValueError("region minimum exceeds maximum")
        return self

    @property
    def volume(self) -> int:
        return int(
            (self.max.x - self.min.x + 1)
            * (self.max.y - self.min.y + 1)
            * (self.max.z - self.min.z + 1)
        )


class RegionInspectionRequest(V2ContractModel):
    schema_version: Literal["2"] = "2"
    transport_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    step_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    bounds: RegionBounds
    maximum_volume: int = Field(gt=0, le=4096)
    deadline_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def _bounded_volume(self) -> RegionInspectionRequest:
        if self.bounds.volume > self.maximum_volume:
            raise ValueError("region exceeds maximum region volume")
        return self


class ActionInspectionRequest(V2ContractModel):
    schema_version: Literal["2"] = "2"
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)


class CancellationRequest(ActionInspectionRequest):
    reason: str = Field(default="controller cancellation", max_length=500)
