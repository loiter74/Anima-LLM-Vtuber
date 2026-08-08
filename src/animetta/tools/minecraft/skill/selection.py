"""Applicability-first deterministic selection of immutable skill revisions."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.tools.minecraft.voyager.goal_models import GoalSpec

from .applicability import (
    ObservationPrerequisite,
    ParameterBinding,
    SkillApplicability,
    TargetPattern,
)
from .ir import SkillRevision
from .trust import SkillEnvironmentTrust

ExclusionReason = Literal[
    "INTENT_MISMATCH",
    "TARGET_MISMATCH",
    "CAPABILITY_MISSING",
    "DISCOVERY_PREREQUISITE_MISSING",
    "TECHNOLOGY_PREREQUISITE_MISSING",
    "ENVIRONMENT_TRUST_MISSING",
    "OBSERVATION_PRECONDITION_MISSING",
    "POLICY_FORBIDDEN",
]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SkillSelectionCandidate(_FrozenModel):
    revision: SkillRevision
    applicability: SkillApplicability
    trust: SkillEnvironmentTrust

    @model_validator(mode="after")
    def _same_immutable_revision(self) -> Self:
        hashes = {
            self.revision.revision_hash,
            self.applicability.revision_hash,
            self.trust.revision_hash,
        }
        if len(hashes) != 1:
            raise ValueError("skill selection records reference different revisions")
        return self


class SkillSelectionContext(_FrozenModel):
    goal: GoalSpec
    environment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_capabilities: frozenset[str]
    discovery_states: dict[str, Literal["observed", "acquired"]] = Field(default_factory=dict)
    technology_nodes: frozenset[str] = frozenset()
    observation: dict[str, Any] = Field(default_factory=dict)
    allow_skill_reuse: bool


class SkillSelectionExclusion(_FrozenModel):
    revision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: ExclusionReason


class SkillSelectionResult(_FrozenModel):
    selected_revision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ordered_revision_hashes: tuple[str, ...] = ()
    bound_parameters: dict[str, object] = Field(default_factory=dict)
    exclusions: tuple[SkillSelectionExclusion, ...] = ()


def _target_matches(pattern: TargetPattern, target: str) -> bool:
    if pattern.kind == "exact":
        return target == pattern.value
    return target.startswith(pattern.value)


def _read_path(observation: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = observation
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _observation_satisfies(
    prerequisite: ObservationPrerequisite, observation: dict[str, Any]
) -> bool:
    present, current = _read_path(observation, prerequisite.path)
    if prerequisite.op == "present":
        return present
    if not present:
        return False
    if prerequisite.op == "equals":
        return current == prerequisite.value
    if prerequisite.op == "contains":
        try:
            return prerequisite.value in current
        except TypeError:
            return False
    try:
        return current >= prerequisite.value
    except TypeError:
        return False


def _discovery_key(fact_kind: str, fact_key: str) -> str:
    return f"{fact_kind}:{fact_key}"


def _applicability_reason(
    candidate: SkillSelectionCandidate, context: SkillSelectionContext
) -> ExclusionReason | None:
    applicability = candidate.applicability
    if context.goal.intent not in applicability.intents:
        return "INTENT_MISMATCH"
    if not any(
        _target_matches(pattern, context.goal.target) for pattern in applicability.target_patterns
    ):
        return "TARGET_MISMATCH"
    if not applicability.required_capabilities.issubset(context.available_capabilities):
        return "CAPABILITY_MISSING"
    state_rank = {"observed": 0, "acquired": 1}
    for prerequisite in applicability.discovery_prerequisites:
        current = context.discovery_states.get(
            _discovery_key(prerequisite.fact_kind, prerequisite.fact_key)
        )
        if current is None or state_rank[current] < state_rank[prerequisite.minimum_state]:
            return "DISCOVERY_PREREQUISITE_MISSING"
    if not applicability.technology_prerequisites.issubset(context.technology_nodes):
        return "TECHNOLOGY_PREREQUISITE_MISSING"
    return None


def _bind_parameter(binding: ParameterBinding, context: SkillSelectionContext) -> object:
    if binding.source == "goal_target":
        return context.goal.target
    if binding.source == "goal_quantity":
        return context.goal.quantity
    assert binding.constraint_key is not None
    return context.goal.constraints[binding.constraint_key]


def select_applicable_skill(
    candidates: tuple[SkillSelectionCandidate, ...],
    context: SkillSelectionContext,
) -> SkillSelectionResult:
    """Filter hard constraints before ranking environment-trusted revisions."""

    eligible: list[SkillSelectionCandidate] = []
    exclusions: list[SkillSelectionExclusion] = []
    for candidate in candidates:
        reason = _applicability_reason(candidate, context)
        if reason is None and not candidate.trust.is_eligible(context.environment_fingerprint):
            reason = "ENVIRONMENT_TRUST_MISSING"
        if reason is None and not all(
            _observation_satisfies(item, context.observation)
            for item in candidate.applicability.observation_prerequisites
        ):
            reason = "OBSERVATION_PRECONDITION_MISSING"
        if reason is None and not context.allow_skill_reuse:
            reason = "POLICY_FORBIDDEN"
        if reason is not None:
            exclusions.append(
                SkillSelectionExclusion(
                    revision_hash=candidate.revision.revision_hash,
                    reason_code=reason,
                )
            )
            continue
        eligible.append(candidate)

    ranked = sorted(
        eligible,
        key=lambda item: (
            -item.trust.wilson_reliability,
            item.trust.expected_cost,
            item.revision.static_cost.max_actions,
            item.revision.revision_hash,
        ),
    )
    if not ranked:
        return SkillSelectionResult(exclusions=tuple(exclusions))
    selected = ranked[0]
    return SkillSelectionResult(
        selected_revision_hash=selected.revision.revision_hash,
        ordered_revision_hashes=tuple(item.revision.revision_hash for item in ranked),
        bound_parameters={
            binding.parameter: _bind_parameter(binding, context)
            for binding in selected.applicability.parameter_bindings
        },
        exclusions=tuple(exclusions),
    )
