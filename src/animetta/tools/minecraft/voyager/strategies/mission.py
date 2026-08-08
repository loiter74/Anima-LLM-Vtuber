"""Mission-policy strategy selection without a second execution owner."""

from __future__ import annotations

from animetta.tools.gamebot.contracts.v2 import Observation

from ..goal_models import GoalSpec
from .base import BoundedStrategy, Complete, StrategyDecision, StrategyFailure


class MissionStrategy:
    """Select one authorized bounded strategy from committed observations."""

    def __init__(
        self,
        *,
        builtin: BoundedStrategy | None = None,
        live: BoundedStrategy | None,
        learn: BoundedStrategy | None,
        fallback: BoundedStrategy | None,
    ) -> None:
        self._strategies = {
            name: strategy
            for name, strategy in (
                ("builtin", builtin),
                ("live", live),
                ("learn", learn),
                ("fallback", fallback),
            )
            if strategy is not None
        }

    def prepare(self, goal: GoalSpec | None) -> dict:
        if goal is None:
            raise ValueError("mission strategy requires a structured goal")
        candidates = tuple(
            name for name in ("builtin", "live", "learn", "fallback") if name in self._strategies
        )
        return {
            "goal": goal,
            "candidates": candidates,
            "candidate_index": 0,
            "selected_strategy": None,
            "strategy_state": None,
            "executed_steps": 0,
            "selection_transitions": (),
        }

    def propose(self, state: dict, observation: Observation) -> StrategyDecision:
        while True:
            selected = state.get("selected_strategy")
            if selected is None:
                candidates = state["candidates"]
                index = state["candidate_index"]
                if index >= len(candidates):
                    return StrategyFailure(
                        code="NO_AUTHORIZED_STRATEGY",
                        message="No mission-policy-authorized strategy can satisfy the goal",
                    )
                selected = candidates[index]
                state["selected_strategy"] = selected
                state["strategy_state"] = self._strategies[selected].prepare(state["goal"])
                state["selection_transitions"] = (
                    *state["selection_transitions"],
                    selected,
                )

            decision = self._strategies[selected].propose(
                state["strategy_state"],
                observation,
            )
            if isinstance(decision, Complete):
                return Complete(output={**decision.output, "selected_strategy": selected})
            if not isinstance(decision, StrategyFailure):
                return decision
            if state["executed_steps"] > 0:
                return decision
            state["candidate_index"] += 1
            state["selected_strategy"] = None
            state["strategy_state"] = None

    def accept_result(self, state: dict, result: object) -> dict:
        selected = state["selected_strategy"]
        if not isinstance(selected, str):
            raise ValueError("mission strategy has no selected delegate")
        delegated = self._strategies[selected].accept_result(
            state["strategy_state"],
            result,
        )
        return {
            **state,
            "strategy_state": delegated,
            "executed_steps": state["executed_steps"] + 1,
        }
