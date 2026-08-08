"""Immutable goal applicability declarations for declarative skill revisions."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash
from animetta.tools.minecraft.voyager.goal_models import GoalSpec

from .ir import ActionStep, BranchStep, RepeatStep, SkillRevision

SkillIntent = Literal[
    "acquire",
    "craft",
    "build",
    "travel",
    "combat",
    "survive",
    "learn",
    "discover",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TargetPattern(_FrozenModel):
    """Safe non-regex match pattern for a normalized goal target."""

    kind: Literal["exact", "prefix"]
    value: str = Field(min_length=1, max_length=256)


class ParameterBinding(_FrozenModel):
    """Bind a SkillProgram input to a closed source in the admitted goal."""

    parameter: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    source: Literal["goal_target", "goal_quantity", "goal_constraint"]
    constraint_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")

    @model_validator(mode="after")
    def _constraint_source_matches_key(self) -> Self:
        if (self.source == "goal_constraint") != (self.constraint_key is not None):
            raise ValueError("goal_constraint binding requires exactly one constraint key")
        return self


class DiscoveryPrerequisite(_FrozenModel):
    fact_kind: Literal[
        "item",
        "block",
        "entity",
        "biome",
        "structure",
        "recipe",
        "advancement",
    ]
    fact_key: str = Field(min_length=1, max_length=256)
    minimum_state: Literal["observed", "acquired"]


class ObservationPrerequisite(_FrozenModel):
    path: str = Field(min_length=1, max_length=256)
    op: Literal["present", "equals", "gte", "contains"]
    value: str | int | float | bool | None = None

    @model_validator(mode="after")
    def _present_has_no_comparison_value(self) -> Self:
        if self.op == "present" and self.value is not None:
            raise ValueError("present observation prerequisite cannot compare a value")
        return self


class SkillApplicability(_FrozenModel):
    """Content-addressed applicability bound to one immutable revision hash."""

    schema_version: Literal["1"] = "1"
    revision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intents: frozenset[SkillIntent] = Field(min_length=1)
    target_patterns: tuple[TargetPattern, ...] = Field(min_length=1, max_length=32)
    parameter_bindings: tuple[ParameterBinding, ...] = Field(max_length=32)
    required_capabilities: frozenset[str] = Field(min_length=1)
    discovery_prerequisites: tuple[DiscoveryPrerequisite, ...] = Field(default=(), max_length=32)
    technology_prerequisites: frozenset[str] = Field(default=frozenset(), max_length=32)
    observation_prerequisites: tuple[ObservationPrerequisite, ...] = Field(
        default=(), max_length=32
    )

    @model_validator(mode="after")
    def _unique_parameter_bindings(self) -> Self:
        parameters = [binding.parameter for binding in self.parameter_bindings]
        if len(parameters) != len(set(parameters)):
            raise ValueError("duplicate parameter binding")
        return self

    @property
    def applicability_hash(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))


def _step_capabilities(steps: tuple[object, ...]) -> frozenset[str]:
    capabilities: set[str] = set()
    for step in steps:
        if isinstance(step, ActionStep):
            capabilities.add(step.capability)
        elif isinstance(step, BranchStep):
            capabilities.update(_step_capabilities(step.then_steps))
            capabilities.update(_step_capabilities(step.else_steps))
        elif isinstance(step, RepeatStep):
            capabilities.update(_step_capabilities(step.steps))
    return frozenset(capabilities)


def applicability_for_goal(
    revision: SkillRevision,
    goal: GoalSpec,
) -> SkillApplicability:
    """Derive a conservative exact-goal declaration for a learned revision."""

    bindings: list[ParameterBinding] = []
    for parameter in revision.program.parameters:
        if parameter.name in {"target", "resource"}:
            bindings.append(ParameterBinding(parameter=parameter.name, source="goal_target"))
        elif parameter.name in {"quantity", "count"}:
            bindings.append(ParameterBinding(parameter=parameter.name, source="goal_quantity"))
        elif parameter.name in goal.constraints:
            bindings.append(
                ParameterBinding(
                    parameter=parameter.name,
                    source="goal_constraint",
                    constraint_key=parameter.name,
                )
            )
        elif parameter.required and parameter.default is None:
            raise ValueError(f"UNBOUND_SKILL_PARAMETER: {parameter.name}")
    return SkillApplicability(
        revision_hash=revision.revision_hash,
        intents=frozenset({goal.intent}),
        target_patterns=(TargetPattern(kind="exact", value=goal.target),),
        parameter_bindings=tuple(bindings),
        required_capabilities=_step_capabilities(revision.program.steps),
    )
