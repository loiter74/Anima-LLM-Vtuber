"""Pure bounded exploration proposal decisions over committed projections."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash
from animetta.tools.minecraft.mission.models import GoalProposal
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.goal_models import GoalSpec

ExplorationSource = Literal[
    "mission_gap",
    "technology_frontier",
    "new_fact",
    "skill_gap",
    "unvisited_frontier",
    "recovery_prerequisite",
]
ExplorationOutcome = Literal[
    "CANDIDATES_READY",
    "NOVELTY_EXHAUSTED",
    "OBSERVATION_ALREADY_CONSUMED",
    "WAITING_COMMITTED_OBSERVATION",
]

_RATIONALE_BY_SOURCE = {
    "mission_gap": "MISSION_GAP",
    "technology_frontier": "TECHNOLOGY_FRONTIER",
    "new_fact": "DISCOVERY_GAP",
    "skill_gap": "SKILL_GAP",
    "unvisited_frontier": "UNVISITED_FRONTIER",
    "recovery_prerequisite": "RECOVERY_PREREQUISITE",
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExplorationBounds(_FrozenModel):
    """Finite bounds applied before a proposal reaches mission admission."""

    max_candidates: int = Field(ge=1, le=16)
    min_expected_value: float = Field(ge=0, le=1)


class ExplorationSeed(_FrozenModel):
    """One schema-valid candidate supplied by a deterministic domain projection."""

    source: ExplorationSource
    signal_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    goal: GoalSpec
    evidence_refs: tuple[str, ...] = ()
    conservative_cost: BudgetUsage
    expected_value: float = Field(ge=0, le=1)


class ExplorationInput(_FrozenModel):
    """Complete immutable input to one observation-driven proposal decision."""

    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    observation_ref: str = Field(min_length=1, max_length=256)
    observation_committed: bool
    mission_gaps: tuple[ExplorationSeed, ...] = ()
    technology_frontier: tuple[ExplorationSeed, ...] = ()
    new_facts: tuple[ExplorationSeed, ...] = ()
    skill_gaps: tuple[ExplorationSeed, ...] = ()
    unvisited_frontier: tuple[ExplorationSeed, ...] = ()
    recovery_prerequisites: tuple[ExplorationSeed, ...] = ()
    proposed_goal_hashes: frozenset[str] = frozenset()
    consumed_observation_refs: frozenset[str] = frozenset()


class ExplorationDecision(_FrozenModel):
    """Bounded candidate set plus the single proposal eligible for admission."""

    outcome: ExplorationOutcome
    observation_ref: str
    candidates: tuple[GoalProposal, ...] = ()
    proposal: GoalProposal | None = None
    rejected_counts: dict[str, int] = Field(default_factory=dict)


def _proposal_id(inputs: ExplorationInput, seed: ExplorationSeed) -> str:
    digest = canonical_json_hash(
        {
            "mission_id": inputs.mission_id,
            "observation_ref": inputs.observation_ref,
            "signal_id": seed.signal_id,
            "goal_hash": seed.goal.canonical_hash,
        }
    )
    return f"auto-{digest[:24]}"


def _evidence_refs(inputs: ExplorationInput, seed: ExplorationSeed) -> tuple[str, ...]:
    return tuple(dict.fromkeys((inputs.observation_ref, *seed.evidence_refs)))


class ExplorationProposer:
    """Generate and select bounded children without performing admission or I/O."""

    def __init__(self, bounds: ExplorationBounds) -> None:
        self._bounds = bounds

    def propose(self, inputs: ExplorationInput) -> ExplorationDecision:
        """Return at most one proposal for the latest committed observation."""

        empty_counts = {"duplicate": 0, "below_value": 0, "over_count": 0}
        if not inputs.observation_committed:
            return ExplorationDecision(
                outcome="WAITING_COMMITTED_OBSERVATION",
                observation_ref=inputs.observation_ref,
                rejected_counts=empty_counts,
            )
        if inputs.observation_ref in inputs.consumed_observation_refs:
            return ExplorationDecision(
                outcome="OBSERVATION_ALREADY_CONSUMED",
                observation_ref=inputs.observation_ref,
                rejected_counts=empty_counts,
            )

        seeds = (
            *inputs.mission_gaps,
            *inputs.technology_frontier,
            *inputs.new_facts,
            *inputs.skill_gaps,
            *inputs.unvisited_frontier,
            *inputs.recovery_prerequisites,
        )
        ordered = sorted(
            enumerate(seeds),
            key=lambda item: (-item[1].expected_value, item[0]),
        )
        counts = dict(empty_counts)
        seen_hashes = set(inputs.proposed_goal_hashes)
        proposals: list[GoalProposal] = []
        for _, seed in ordered:
            if seed.expected_value < self._bounds.min_expected_value:
                counts["below_value"] += 1
                continue
            goal_hash = seed.goal.canonical_hash
            if goal_hash in seen_hashes:
                counts["duplicate"] += 1
                continue
            seen_hashes.add(goal_hash)
            if len(proposals) >= self._bounds.max_candidates:
                counts["over_count"] += 1
                continue
            proposals.append(
                GoalProposal.model_validate(
                    {
                        "proposal_id": _proposal_id(inputs, seed),
                        "mission_id": inputs.mission_id,
                        "origin": (
                            "recovery" if seed.source == "recovery_prerequisite" else "curriculum"
                        ),
                        "goal": seed.goal,
                        "rationale_code": _RATIONALE_BY_SOURCE[seed.source],
                        "evidence_refs": _evidence_refs(inputs, seed),
                        "conservative_cost": seed.conservative_cost,
                        "expected_value": seed.expected_value,
                    }
                )
            )

        candidates = tuple(proposals)
        if not candidates:
            return ExplorationDecision(
                outcome="NOVELTY_EXHAUSTED",
                observation_ref=inputs.observation_ref,
                rejected_counts=counts,
            )
        return ExplorationDecision(
            outcome="CANDIDATES_READY",
            observation_ref=inputs.observation_ref,
            candidates=candidates,
            proposal=candidates[0],
            rejected_counts=counts,
        )
