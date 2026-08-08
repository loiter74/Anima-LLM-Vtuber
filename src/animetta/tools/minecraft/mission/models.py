"""Versioned contracts for bounded adaptive Minecraft missions."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash
from animetta.tools.minecraft.voyager.budget import (
    BudgetUsage,
    ExecutionBudget,
)
from animetta.tools.minecraft.voyager.goal_models import GoalSpec


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @property
    def canonical_hash(self) -> str:
        """Return a stable hash of the canonical JSON representation."""

        return canonical_json_hash(self.canonical_payload())

    def canonical_payload(self) -> dict[str, object]:
        """Return JSON-compatible data with deterministic set ordering."""

        return cast(
            dict[str, object],
            _canonical_value(self.model_dump(mode="python", exclude_none=True)),
        )


def _canonical_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        normalized = [_canonical_value(item) for item in value]
        return sorted(normalized, key=lambda item: str(item))
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


class NovelFactsAcquiredAtLeast(_FrozenModel):
    kind: Literal["novel_facts_acquired_at_least"]
    count: int = Field(gt=0)


class TrustedSkillsCreatedAtLeast(_FrozenModel):
    kind: Literal["trusted_skills_created_at_least"]
    count: int = Field(gt=0)


class VanillaAdvancementsAddedAtLeast(_FrozenModel):
    kind: Literal["vanilla_advancements_added_at_least"]
    count: int = Field(gt=0)


MissionCompletionPredicate = (
    NovelFactsAcquiredAtLeast | TrustedSkillsCreatedAtLeast | VanillaAdvancementsAddedAtLeast
)


class AutonomyPolicy(_FrozenModel):
    mode: Literal["off", "bounded"] = "off"
    allowed_domains: frozenset[Literal["discovery", "skill", "technology", "recovery"]] = (
        frozenset()
    )
    max_child_goals: int = Field(default=0, ge=0, le=64)
    max_new_skills: int = Field(default=0, ge=0, le=16)
    max_duration_ms: int = Field(default=0, ge=0, le=3_600_000)
    max_travel_distance: float = Field(default=0, ge=0, le=10_000)
    max_damage_taken: float = Field(default=0, ge=0, le=20)
    max_blocks_changed: int = Field(default=0, ge=0, le=4096)
    max_risk: Literal["read_only", "survival_safe", "destructive"] = "read_only"
    stop_conditions: frozenset[
        Literal[
            "mission_complete",
            "novelty_exhausted",
            "budget_exhausted",
            "user_stop",
            "unknown_world_state",
        ]
    ] = frozenset()

    @model_validator(mode="after")
    def _finite_bounded_authority(self) -> Self:
        if self.mode == "bounded" and (
            not self.allowed_domains
            or self.max_child_goals == 0
            or self.max_duration_ms == 0
            or not self.stop_conditions
        ):
            raise ValueError("bounded autonomy requires finite authority and stop conditions")
        if self.mode == "off" and any(
            (
                self.allowed_domains,
                self.max_child_goals,
                self.max_new_skills,
                self.max_duration_ms,
                self.max_travel_distance,
                self.max_damage_taken,
                self.max_blocks_changed,
                self.stop_conditions,
            )
        ):
            raise ValueError("autonomy off cannot retain autonomous authority")
        return self


class ExecutionPolicy(_FrozenModel):
    reuse_trusted_skill: bool = True
    allow_skill_learning: bool = False
    allow_deterministic_fallback: bool = False


class MissionObjective(_FrozenModel):
    objective_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    goal: GoalSpec
    dependencies: tuple[str, ...] = ()
    required: bool = True
    priority: int = Field(default=50, ge=0, le=100)
    budget: BudgetUsage

    @field_validator("dependencies")
    @classmethod
    def _valid_dependencies(cls, dependencies: tuple[str, ...]) -> tuple[str, ...]:
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("duplicate dependency")
        return dependencies


def _usage_sum(usages: tuple[BudgetUsage, ...]) -> BudgetUsage:
    total = BudgetUsage()
    for usage in usages:
        total = total.plus(usage)
    return total


def _usage_fits_parent(usage: BudgetUsage, parent: ExecutionBudget) -> bool:
    scalar_fields = (
        "max_actions",
        "max_strategy_attempts",
        "max_travel_distance",
        "max_blocks_changed",
        "max_damage_taken",
    )
    if any(getattr(usage, field) > getattr(parent, field) for field in scalar_fields):
        return False
    return all(
        amount <= parent.resource_consumption.get(resource, 0)
        for resource, amount in usage.resource_consumption.items()
    )


class MissionSpec(_FrozenModel):
    schema_version: Literal["1"] = "1"
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    objectives: tuple[MissionObjective, ...] = Field(min_length=1, max_length=128)
    allowed_domains: frozenset[
        Literal["gameplay", "discovery", "skill", "technology", "recovery"]
    ] = frozenset({"gameplay", "discovery", "skill", "technology", "recovery"})
    completion_rule: Literal["all_required"] = "all_required"
    completion_predicates: tuple[
        NovelFactsAcquiredAtLeast | TrustedSkillsCreatedAtLeast | VanillaAdvancementsAddedAtLeast,
        ...,
    ] = ()
    budget: ExecutionBudget
    autonomy: AutonomyPolicy = AutonomyPolicy()
    execution: ExecutionPolicy = ExecutionPolicy()

    @field_validator("budget", mode="before")
    @classmethod
    def _normalize_protected_items(cls, budget: object) -> object:
        if isinstance(budget, dict) and isinstance(budget.get("protected_items"), list):
            return {**budget, "protected_items": frozenset(budget["protected_items"])}
        return budget

    @model_validator(mode="after")
    def _valid_dag_and_budget(self) -> Self:
        by_id = {objective.objective_id: objective for objective in self.objectives}
        if len(by_id) != len(self.objectives):
            raise ValueError("duplicate objective ID")
        for objective in self.objectives:
            unknown = set(objective.dependencies) - set(by_id)
            if unknown:
                raise ValueError(f"unknown dependency: {sorted(unknown)!r}")
            if objective.objective_id in objective.dependencies:
                raise ValueError("dependency cycle")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(objective_id: str) -> None:
            if objective_id in visiting:
                raise ValueError("dependency cycle")
            if objective_id in visited:
                return
            visiting.add(objective_id)
            for dependency in by_id[objective_id].dependencies:
                visit(dependency)
            visiting.remove(objective_id)
            visited.add(objective_id)

        for objective_id in by_id:
            visit(objective_id)

        reserved = _usage_sum(tuple(objective.budget for objective in self.objectives))
        if not _usage_fits_parent(reserved, self.budget):
            raise ValueError("child budgets exceed parent mission budget")
        return self


class GoalProposal(_FrozenModel):
    schema_version: Literal["1"] = "1"
    proposal_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    origin: Literal["user", "scenario", "curriculum", "recovery"]
    parent_objective_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    goal: GoalSpec
    rationale_code: Literal[
        "USER_REQUEST",
        "SCENARIO_REQUIREMENT",
        "MISSION_GAP",
        "DISCOVERY_GAP",
        "SKILL_GAP",
        "TECHNOLOGY_FRONTIER",
        "RECOVERY_PREREQUISITE",
        "UNVISITED_FRONTIER",
    ]
    evidence_refs: tuple[str, ...] = ()
    conservative_cost: BudgetUsage
    expected_value: float = Field(ge=0, le=1)


class GoalAdmissionDecision(_FrozenModel):
    schema_version: Literal["1"] = "1"
    proposal_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    outcome: Literal["accepted", "rejected", "deferred"]
    reason_code: Literal[
        "ADMITTED",
        "INVALID_SCHEMA",
        "SOURCE_FORBIDDEN",
        "DOMAIN_FORBIDDEN",
        "DEPENDENCY_UNSATISFIED",
        "DUPLICATE_PROPOSAL",
        "MANIFEST_CAPABILITY_MISSING",
        "RISK_FORBIDDEN",
        "RUNTIME_QUARANTINED",
        "BUDGET_EXHAUSTED",
        "CHILD_GOAL_LIMIT_REACHED",
    ]
    reserved_budget: BudgetUsage | None = None

    @model_validator(mode="after")
    def _reservation_matches_outcome(self) -> Self:
        if (self.outcome == "accepted") != (self.reserved_budget is not None):
            raise ValueError("only accepted proposals reserve budget")
        return self


class EvidenceRef(_FrozenModel):
    schema_version: Literal["1"] = "1"
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    artifact_kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    json_pointer: str = Field(min_length=1, max_length=512, pattern=r"^(?:/[^/]*)+$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerificationPredicate(_FrozenModel):
    predicate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    expected: object
    actual: object | None = None
    status: Literal["pass", "fail", "unknown"]


class StageStateDelta(_FrozenModel):
    path: str = Field(min_length=1, max_length=256)
    before: object | None = None
    after: object | None = None


class StageFailure(_FrozenModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    layer: Literal[
        "scenario",
        "capture",
        "conversation",
        "admission",
        "execution",
        "observation",
        "reconciliation",
        "verification",
        "presentation",
    ]
    retryable: bool
    operator_action: str = Field(min_length=1, max_length=512)


class StageMedia(_FrozenModel):
    evidence_ref: EvidenceRef
    captured_at_ms: int = Field(ge=0)


class CheckpointIO(_FrozenModel):
    schema_version: Literal["1"] = "1"
    checkpoint_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    label: str = Field(min_length=1, max_length=128)
    lifecycle: Literal["pending", "running", "passed", "failed", "blocked", "skipped"]
    input_refs: tuple[EvidenceRef, ...] = ()
    decision_source: str | None = Field(default=None, min_length=1, max_length=128)
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    selected_strategy: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,127}$")
    selected_capability: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    output_refs: tuple[EvidenceRef, ...] = ()
    verifier: str | None = Field(default=None, min_length=1, max_length=128)
    predicates: tuple[VerificationPredicate, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    failure: StageFailure | None = None

    @model_validator(mode="after")
    def _failure_matches_lifecycle(self) -> Self:
        if self.lifecycle in {"failed", "blocked"} and self.failure is None:
            raise ValueError("failed or blocked checkpoint requires failure")
        if self.lifecycle not in {"failed", "blocked"} and self.failure is not None:
            raise ValueError("checkpoint failure requires failed or blocked lifecycle")
        return self


class StageIO(_FrozenModel):
    schema_version: Literal["2"] = "2"
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    stage_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    ordinal: int = Field(ge=1)
    gameplay_evidence_eligible: bool
    lifecycle: Literal["pending", "running", "passed", "failed", "blocked", "skipped"]
    started_at_ms: int | None = Field(default=None, ge=0)
    finished_at_ms: int | None = Field(default=None, ge=0)
    input_refs: tuple[EvidenceRef, ...] = ()
    decision_source: str | None = Field(default=None, min_length=1, max_length=128)
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    selected_strategy: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,127}$")
    selected_capability: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    budget_ref: EvidenceRef | None = None
    output_refs: tuple[EvidenceRef, ...] = ()
    state_deltas: tuple[StageStateDelta, ...] = ()
    verifier: str | None = Field(default=None, min_length=1, max_length=128)
    predicates: tuple[VerificationPredicate, ...] = ()
    checkpoints: tuple[CheckpointIO, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    media: tuple[StageMedia, ...] = ()
    failure: StageFailure | None = None

    @model_validator(mode="after")
    def _consistent_stage(self) -> Self:
        if (
            self.started_at_ms is not None
            and self.finished_at_ms is not None
            and self.finished_at_ms < self.started_at_ms
        ):
            raise ValueError("stage finish precedes start")
        if self.lifecycle == "pending" and self.finished_at_ms is not None:
            raise ValueError("pending stage cannot have a finish timestamp")
        if self.lifecycle == "running" and self.started_at_ms is None:
            raise ValueError("running stage requires a start timestamp")
        if self.lifecycle in {"passed", "failed", "blocked"} and (
            self.started_at_ms is None or self.finished_at_ms is None
        ):
            raise ValueError("terminal stage requires start and finish timestamps")
        if self.lifecycle in {"failed", "blocked"} and self.failure is None:
            raise ValueError("failed or blocked stage requires failure")
        if self.lifecycle not in {"failed", "blocked"} and self.failure is not None:
            raise ValueError("stage failure requires failed or blocked lifecycle")
        if (
            self.started_at_ms is not None
            and self.finished_at_ms is not None
            and any(
                item.captured_at_ms < self.started_at_ms
                or item.captured_at_ms > self.finished_at_ms
                for item in self.media
            )
        ):
            raise ValueError("media timestamp is outside the stage")
        return self


class StageDefinition(_FrozenModel):
    stage_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    ordinal: int = Field(ge=1)
    required: bool = True
    gameplay_evidence_eligible: bool = True
    checkpoint_ids: tuple[str, ...] = ()


class WalkthroughManifest(_FrozenModel):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stages: tuple[StageIO, ...]
    bundle_valid: bool
    acceptance_passed: bool

    @model_validator(mode="after")
    def _consistent_verdicts(self) -> Self:
        if len({stage.stage_id for stage in self.stages}) != len(self.stages):
            raise ValueError("walkthrough contains duplicate stage IDs")
        if tuple(stage.ordinal for stage in self.stages) != tuple(
            sorted(stage.ordinal for stage in self.stages)
        ):
            raise ValueError("walkthrough stages are not in ordinal order")
        if any(
            stage.run_id != self.run_id or stage.mission_id != self.mission_id
            for stage in self.stages
        ):
            raise ValueError("walkthrough stage identity mismatch")
        if self.acceptance_passed and (
            not self.bundle_valid or any(stage.lifecycle != "passed" for stage in self.stages)
        ):
            raise ValueError("acceptance cannot pass without a valid all-passed bundle")
        return self


class MissionReport(_FrozenModel):
    schema_version: Literal["1"] = "1"
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    status: Literal[
        "accepted",
        "planning",
        "running",
        "waiting_evidence",
        "completed",
        "failed",
        "cancelled",
        "blocked_unknown",
    ]
    objective_counts: dict[str, int] = Field(default_factory=dict)
    proposal_counts: dict[str, int] = Field(default_factory=dict)
    budget_used: BudgetUsage = BudgetUsage()
    evidence_refs: tuple[str, ...] = ()
    stage_ids: tuple[str, ...] = ()

    @field_validator("objective_counts", "proposal_counts")
    @classmethod
    def _non_negative_counts(cls, counts: dict[str, int]) -> dict[str, int]:
        if any(value < 0 for value in counts.values()):
            raise ValueError("report counts must be non-negative")
        return counts
