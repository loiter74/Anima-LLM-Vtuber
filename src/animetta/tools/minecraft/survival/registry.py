"""Exact GoalSpec-to-deterministic-workflow registry."""

from __future__ import annotations

from animetta.tools.minecraft.voyager.goal_models import GoalSpec

from .workflows import WorkflowDefinition


class WorkflowRegistry:
    def __init__(self) -> None:
        self._workflows: dict[tuple[str, str], WorkflowDefinition] = {}

    def register(self, workflow: WorkflowDefinition) -> None:
        key = (workflow.intent, workflow.target)
        if key in self._workflows:
            raise ValueError(f"duplicate workflow registration: {key}")
        self._workflows[key] = workflow

    def resolve(self, goal: GoalSpec) -> WorkflowDefinition | None:
        return self._workflows.get((goal.intent, goal.target))
