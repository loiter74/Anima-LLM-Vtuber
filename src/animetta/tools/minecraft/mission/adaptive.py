"""Pure adaptive-mission decisions over committed world and skill projections."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.minecraft.discovery.exploration import (
    ExplorationInput,
    ExplorationSeed,
)
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.goal_models import (
    AcquireGoal,
    InventoryAtLeast,
    LocationReached,
    TravelGoal,
)

AdaptivePhase = Literal["explore", "learn_validate", "reuse"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExplorationFrontier(_FrozenModel):
    """Finite domain seed selected before mission execution starts."""

    x: float
    y: float
    z: float
    target_block: str = Field(pattern=r"^[a-z0-9_:.-]+$")
    target_item: str = Field(pattern=r"^[a-z0-9_:.-]+$")


class AdaptiveMissionState(_FrozenModel):
    """Only durable/committed projections consulted by the policy."""

    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    observation_ref: str = Field(min_length=1, max_length=256)
    observed_fact_keys: frozenset[str] = frozenset()
    acquired_fact_ids: frozenset[str] = frozenset()
    trusted_revision_hashes: frozenset[str] = frozenset()
    inventory: dict[str, int] = Field(default_factory=dict)
    completed_adaptive_phases: frozenset[AdaptivePhase] = frozenset()


class AdaptiveMissionDecision(_FrozenModel):
    exploration: ExplorationInput | None = None
    ready_for_verification: bool = False
    stop_reason: Literal["NOVELTY_EXHAUSTED"] | None = None


class AdaptiveMissionPolicy:
    """Derive one next child from the latest committed observation."""

    def __init__(self, *, frontier: ExplorationFrontier) -> None:
        self._frontier = frontier

    def decide(self, state: AdaptiveMissionState) -> AdaptiveMissionDecision:
        if "reuse" in state.completed_adaptive_phases:
            return AdaptiveMissionDecision(ready_for_verification=True)

        target_fact = f"block:{self._frontier.target_block}"
        target_observed = target_fact in state.observed_fact_keys
        if not target_observed:
            if "explore" in state.completed_adaptive_phases:
                return AdaptiveMissionDecision(stop_reason="NOVELTY_EXHAUSTED")
            return AdaptiveMissionDecision(
                exploration=self._exploration_input(
                    state,
                    unvisited_frontier=(self._travel_seed(),),
                )
            )

        if "learn_validate" not in state.completed_adaptive_phases:
            return AdaptiveMissionDecision(
                exploration=self._exploration_input(
                    state,
                    new_facts=(self._learning_seed(),),
                )
            )

        if not state.trusted_revision_hashes or not state.acquired_fact_ids:
            return AdaptiveMissionDecision(stop_reason="NOVELTY_EXHAUSTED")

        return AdaptiveMissionDecision(
            exploration=self._exploration_input(
                state,
                skill_gaps=(self._reuse_seed(state),),
            )
        )

    def _exploration_input(
        self,
        state: AdaptiveMissionState,
        *,
        new_facts: tuple[ExplorationSeed, ...] = (),
        skill_gaps: tuple[ExplorationSeed, ...] = (),
        unvisited_frontier: tuple[ExplorationSeed, ...] = (),
    ) -> ExplorationInput:
        return ExplorationInput(
            mission_id=state.mission_id,
            observation_ref=state.observation_ref,
            observation_committed=True,
            new_facts=new_facts,
            skill_gaps=skill_gaps,
            unvisited_frontier=unvisited_frontier,
        )

    def _travel_seed(self) -> ExplorationSeed:
        frontier = self._frontier
        return ExplorationSeed(
            source="unvisited_frontier",
            signal_id="adaptive-hidden-resource-frontier",
            goal=TravelGoal(
                intent="travel",
                target="unvisited resource frontier",
                constraints={"adaptive_phase": "explore"},
                success_predicates=(
                    LocationReached(
                        kind="location_reached",
                        x=frontier.x,
                        y=frontier.y,
                        z=frontier.z,
                        tolerance=3,
                    ),
                ),
            ),
            conservative_cost=BudgetUsage(
                max_actions=1,
                max_strategy_attempts=1,
                max_travel_distance=64,
            ),
            expected_value=0.9,
        )

    def _learning_seed(self) -> ExplorationSeed:
        frontier = self._frontier
        return ExplorationSeed(
            source="new_fact",
            signal_id="adaptive-new-resource-acquisition",
            goal=AcquireGoal(
                intent="acquire",
                target=frontier.target_item,
                quantity=1,
                constraints={
                    "adaptive_phase": "learn_validate",
                    "source_block": frontier.target_block,
                },
                success_predicates=(
                    InventoryAtLeast(
                        kind="inventory_at_least",
                        item=frontier.target_item,
                        quantity=1,
                    ),
                ),
            ),
            conservative_cost=BudgetUsage(
                max_actions=2,
                max_strategy_attempts=2,
                max_travel_distance=64,
                max_blocks_changed=2,
            ),
            expected_value=0.95,
        )

    def _reuse_seed(self, state: AdaptiveMissionState) -> ExplorationSeed:
        frontier = self._frontier
        quantity = max(1, state.inventory.get(frontier.target_item, 0)) + 1
        return ExplorationSeed(
            source="skill_gap",
            signal_id="adaptive-trusted-skill-reuse",
            goal=AcquireGoal(
                intent="acquire",
                target=frontier.target_item,
                quantity=quantity,
                constraints={
                    "adaptive_phase": "reuse",
                    "source_block": frontier.target_block,
                },
                success_predicates=(
                    InventoryAtLeast(
                        kind="inventory_at_least",
                        item=frontier.target_item,
                        quantity=quantity,
                    ),
                ),
            ),
            conservative_cost=BudgetUsage(
                max_actions=1,
                max_strategy_attempts=1,
                max_travel_distance=64,
                max_blocks_changed=1,
            ),
            expected_value=1,
        )
