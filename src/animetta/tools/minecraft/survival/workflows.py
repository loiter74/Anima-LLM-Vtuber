"""Typed deterministic workflows adapted from the survival runner phases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.strategies.base import ExecuteStep


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    workflow_id: str
    intent: str
    target: str
    steps: tuple[ExecuteStep, ...]


def _step(capability: str, parameters: dict, *, travel: float = 0, blocks: int = 0):
    return ExecuteStep(
        capability=capability,
        parameters=parameters,
        maximum_cost=BudgetUsage(
            max_actions=1,
            max_travel_distance=travel,
            max_blocks_changed=blocks,
        ),
    )


def iron_survival_workflow() -> WorkflowDefinition:
    """The existing wood-to-iron sequence expressed as bounded typed steps."""

    return WorkflowDefinition(
        workflow_id="survival:iron",
        intent="acquire",
        target="iron_ingot",
        steps=(
            _step("collect", {"block_type": "oak_log", "count": 5}, travel=64, blocks=5),
            _step("craft", {"recipe": "oak_planks", "count": 4}),
            _step("craft", {"recipe": "crafting_table", "count": 1}),
            _step("craft", {"recipe": "stick", "count": 4}),
            _step("craft", {"recipe": "wooden_pickaxe", "count": 1}),
            _step("collect", {"block_type": "stone", "count": 12}, travel=48, blocks=12),
            _step("craft", {"recipe": "stone_pickaxe", "count": 1}),
            _step("craft", {"recipe": "furnace", "count": 1}),
            _step("collect", {"block_type": "coal_ore", "count": 3}, travel=64, blocks=3),
            _step("collect", {"block_type": "iron_ore", "count": 3}, travel=96, blocks=3),
            _step("smelt", {"item": "raw_iron", "fuel": "coal", "count": 3}),
        ),
    )
