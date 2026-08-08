"""One-shot strategy for a caller-supplied manifest capability."""

from __future__ import annotations

from jsonschema import validate as validate_json

from animetta.tools.gamebot.contracts.v2 import (
    CapabilityDefinition,
    Observation,
    RuntimeManifest,
)

from ..budget import BudgetUsage
from ..goal_models import AtomicAction, GoalSpec
from .base import Complete, ExecuteStep, StrategyDecision


def _cost(capability: CapabilityDefinition) -> BudgetUsage:
    value = capability.maximum_cost
    return BudgetUsage(
        max_actions=value.max_actions,
        max_strategy_attempts=value.max_strategy_attempts,
        max_travel_distance=value.max_travel_distance,
        max_blocks_changed=value.max_blocks_changed,
        max_damage_taken=value.max_damage_taken,
        resource_consumption=value.resource_consumption,
    )


class AtomicStrategy:
    def __init__(self, *, action: AtomicAction, manifest: RuntimeManifest) -> None:
        capability = manifest.capability(action.capability)
        validate_json(action.parameters, capability.parameters_schema)
        self._action = action
        self._maximum_cost = _cost(capability)

    def prepare(self, goal: GoalSpec | None) -> dict:
        if goal is not None:
            raise ValueError("atomic strategy does not accept a goal")
        return {"proposed": False, "completed": False}

    def propose(self, state: dict, observation: Observation) -> StrategyDecision:
        del observation
        if state.get("completed"):
            return Complete(output={"atomic_action_completed": True})
        return ExecuteStep(
            capability=self._action.capability,
            parameters=self._action.parameters,
            maximum_cost=self._maximum_cost,
        )

    def accept_result(self, state: dict, result: object) -> dict:
        del result
        return {**state, "proposed": True, "completed": True}
