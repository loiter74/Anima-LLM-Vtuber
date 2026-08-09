"""Typed deterministic workflows adapted from the survival runner phases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.strategies.base import ExecuteStep


class InventoryThreshold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    item: str = Field(pattern=r"^[a-z0-9_:.-]+$")
    quantity: int = Field(gt=0)


class WorkflowCheckpointClause(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    inventory_all: tuple[InventoryThreshold, ...] = ()
    maximum_y: int | None = None

    @model_validator(mode="after")
    def require_evidence(self) -> WorkflowCheckpointClause:
        if not self.inventory_all and self.maximum_y is None:
            raise ValueError("workflow checkpoint clause requires observable evidence")
        return self


class WorkflowCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    any_of: tuple[WorkflowCheckpointClause, ...] = Field(min_length=1)


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    workflow_id: str
    intent: str
    target: str
    steps: tuple[ExecuteStep, ...]
    checkpoints: tuple[WorkflowCheckpoint | None, ...] = ()

    @model_validator(mode="after")
    def align_checkpoints(self) -> WorkflowDefinition:
        if self.checkpoints and len(self.checkpoints) != len(self.steps):
            raise ValueError("workflow checkpoints must align with steps")
        return self


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


def _inventory_checkpoint(*alternatives: dict[str, int]) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        any_of=tuple(
            WorkflowCheckpointClause(
                inventory_all=tuple(
                    InventoryThreshold(item=item, quantity=quantity)
                    for item, quantity in requirement.items()
                )
            )
            for requirement in alternatives
        )
    )


def _depth_checkpoint(maximum_y: int) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        any_of=(
            WorkflowCheckpointClause(maximum_y=maximum_y),
            WorkflowCheckpointClause(
                inventory_all=(InventoryThreshold(item="diamond", quantity=1),)
            ),
        )
    )


_BOOTSTRAP_COMPLETE = _inventory_checkpoint(
    {"wooden_pickaxe": 1, "oak_planks": 7, "stick": 4},
    {"stone_pickaxe": 1},
    {"iron_pickaxe": 1},
    {"diamond": 1},
)


def _iron_progression_steps() -> tuple[ExecuteStep, ...]:
    return (
        _step("collect", {"block_type": "oak_log", "count": 8}, travel=64, blocks=8),
        _step("craft", {"recipe": "oak_planks", "count": 32}),
        _step("craft", {"recipe": "crafting_table", "count": 1}),
        _step("craft", {"recipe": "stick", "count": 4}),
        _step("craft", {"recipe": "wooden_pickaxe", "count": 1}),
        _step("collect", {"block_type": "stone", "count": 16}, travel=48, blocks=16),
        _step("craft", {"recipe": "stone_pickaxe", "count": 1}),
        _step("craft", {"recipe": "furnace", "count": 1}),
        _step("collect", {"block_type": "iron_ore", "count": 3}, travel=96, blocks=3),
        _step("smelt", {"item": "raw_iron", "fuel": "oak_planks", "count": 3}),
    )


def _iron_progression_checkpoints() -> tuple[WorkflowCheckpoint, ...]:
    return (
        *(_BOOTSTRAP_COMPLETE,) * 5,
        _inventory_checkpoint(
            {"cobblestone": 11},
            {"stone_pickaxe": 1},
            {"iron_pickaxe": 1},
            {"diamond": 1},
        ),
        _inventory_checkpoint({"stone_pickaxe": 1}, {"iron_pickaxe": 1}, {"diamond": 1}),
        _inventory_checkpoint({"furnace": 1}, {"iron_ingot": 3}, {"iron_pickaxe": 1}),
        _inventory_checkpoint({"raw_iron": 3}, {"iron_ingot": 3}, {"iron_pickaxe": 1}),
        _inventory_checkpoint({"iron_ingot": 3}, {"iron_pickaxe": 1}),
    )


def _bounded_diamond_descent() -> tuple[ExecuteStep, ...]:
    return tuple(
        _step(
            "mine_shaft",
            {"target_y": target_y, "minimum_cobblestone": 0},
            blocks=24,
        )
        for target_y in range(56, -49, -8)
    ) + (
        _step(
            "mine_shaft",
            {"target_y": -54, "minimum_cobblestone": 0},
            blocks=18,
        ),
    )


def _bounded_diamond_descent_checkpoints() -> tuple[WorkflowCheckpoint, ...]:
    return tuple(_depth_checkpoint(target_y) for target_y in range(56, -49, -8)) + (
        _depth_checkpoint(-54),
    )


def iron_survival_workflow() -> WorkflowDefinition:
    """The existing wood-to-iron sequence expressed as bounded typed steps."""

    return WorkflowDefinition(
        workflow_id="survival:iron",
        intent="acquire",
        target="iron_ingot",
        steps=_iron_progression_steps(),
        checkpoints=_iron_progression_checkpoints(),
    )


def diamond_survival_workflow() -> WorkflowDefinition:
    """Bounded typed actions from the survival start through one diamond."""

    return WorkflowDefinition(
        workflow_id="survival:diamond",
        intent="acquire",
        target="diamond",
        steps=(
            *_iron_progression_steps(),
            _step("craft", {"recipe": "stick", "count": 4}),
            _step("craft", {"recipe": "iron_pickaxe", "count": 1}),
            *_bounded_diamond_descent(),
            _step(
                "collect",
                {"block_type": "diamond_ore", "count": 1},
                travel=128,
                blocks=1,
            ),
        ),
        checkpoints=(
            *_iron_progression_checkpoints(),
            _inventory_checkpoint({"stick": 2}, {"iron_pickaxe": 1}, {"diamond": 1}),
            _inventory_checkpoint({"iron_pickaxe": 1}, {"diamond": 1}),
            *_bounded_diamond_descent_checkpoints(),
            _inventory_checkpoint({"diamond": 1}),
        ),
    )
