"""Explicit deterministic workflow strategy with no implicit goal substitution."""

from __future__ import annotations

from animetta.tools.gamebot.contracts.v2 import Observation
from animetta.tools.minecraft.survival.registry import WorkflowRegistry

from ..goal_models import GoalSpec
from .base import Complete, StrategyDecision, StrategyFailure


class FallbackStrategy:
    def __init__(self, *, registry: WorkflowRegistry) -> None:
        self._registry = registry

    def prepare(self, goal: GoalSpec | None) -> dict:
        if goal is None:
            raise ValueError("fallback requires a structured goal")
        workflow = self._registry.resolve(goal)
        if workflow is None:
            return {
                "goal": goal,
                "goal_hash": goal.canonical_hash,
                "failure_code": "UNSUPPORTED_FALLBACK_GOAL",
                "learning_evidence_eligible": False,
            }
        return {
            "goal": goal,
            "goal_hash": goal.canonical_hash,
            "workflow": workflow,
            "step_index": 0,
            "learning_evidence_eligible": False,
        }

    def propose(self, state: dict, observation: Observation) -> StrategyDecision:
        del observation
        if state.get("failure_code"):
            return StrategyFailure(
                code=state["failure_code"], message="No exact deterministic workflow"
            )
        workflow = state["workflow"]
        index = state["step_index"]
        if index >= len(workflow.steps):
            return Complete(
                output={
                    "workflow_id": workflow.workflow_id,
                    "learning_evidence_eligible": False,
                }
            )
        return workflow.steps[index]

    def accept_result(self, state: dict, result: object) -> dict:
        del result
        return {**state, "step_index": state["step_index"] + 1}
