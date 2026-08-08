"""GameBot v2 manifest and stable environment identity."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ._base import V2ContractModel
from .budget import BudgetVector

Hash256 = str


class CapabilityGuarantees(V2ContractModel):
    """Production guarantees required before the controller becomes ready."""

    single_flight: Literal[True]
    correlation_idempotency: Literal[True]
    cooperative_cancellation: Literal[True]
    action_budget_enforcement: Literal[True]
    receipt_chains: Literal[True]
    correlation_inspection: Literal[True]


class EnvironmentProfile(V2ContractModel):
    """Stable compatibility identity; transient world state is deliberately absent."""

    schema_version: Literal["1"] = "1"
    runtime_protocol: Literal["2.0"]
    minecraft_version: str = Field(min_length=1, max_length=64)
    capability_schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    skill_api_version: str = Field(min_length=1, max_length=32)
    policy_version: str = Field(min_length=1, max_length=32)
    server_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    world_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimension: str = Field(min_length=1, max_length=128)
    modset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CapabilityDefinition(V2ContractModel):
    """One schema-bound runtime capability."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    risk: Literal["read_only", "survival_safe", "destructive"]
    effect_class: Literal["read_only", "state_changing"]
    parameters_schema: dict[str, object]
    receipt_schema_version: Literal["2"]
    requires_post_observation: bool
    maximum_cost: BudgetVector


class RuntimeManifest(V2ContractModel):
    """Runtime identity and capabilities validated at readiness."""

    schema_version: Literal["2"] = "2"
    protocol_version: Literal["2.0"] = "2.0"
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    profile: EnvironmentProfile
    guarantees: CapabilityGuarantees
    capabilities: tuple[CapabilityDefinition, ...]

    @model_validator(mode="after")
    def _unique_capabilities(self) -> RuntimeManifest:
        names = [capability.name for capability in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError("manifest capability names must be unique")
        return self

    def capability(self, name: str) -> CapabilityDefinition:
        for capability in self.capabilities:
            if capability.name == name:
                return capability
        raise KeyError(name)
