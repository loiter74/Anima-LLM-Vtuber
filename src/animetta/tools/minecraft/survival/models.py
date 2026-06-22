"""Survival iron-run domain models.

Defines the phase state machine, inventory goals, failure categories,
and run report used by the survival runner.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

if sys.version_info >= (3, 11):  # noqa: UP036
    from enum import StrEnum
else:
    # Python 3.10 compatibility
    class StrEnum(str, Enum):  # type: ignore[no-redef]  # noqa: UP042
        pass


class SurvivalPhase(StrEnum):
    """Phases in the wood-to-iron-gear progression."""

    WOOD = "wood"
    CRAFTING_TABLE = "crafting_table"
    WOODEN_PICKAXE = "wooden_pickaxe"
    COBBLESTONE = "cobblestone"
    STONE_KIT = "stone_kit"
    FUEL = "fuel"
    IRON_ORE = "iron_ore"
    SMELT_IRON = "smelt_iron"
    IRON_GEAR = "iron_gear"
    DONE = "done"


# Ordered phase list for iteration
PHASE_ORDER: list[SurvivalPhase] = [
    SurvivalPhase.WOOD,
    SurvivalPhase.CRAFTING_TABLE,
    SurvivalPhase.WOODEN_PICKAXE,
    SurvivalPhase.COBBLESTONE,
    SurvivalPhase.STONE_KIT,
    SurvivalPhase.FUEL,
    SurvivalPhase.IRON_ORE,
    SurvivalPhase.SMELT_IRON,
    SurvivalPhase.IRON_GEAR,
    SurvivalPhase.DONE,
]


class FailureCategory(StrEnum):
    """Categorizes why a phase action failed."""

    ACTION_FAILED = "action_failed"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    SAFETY_PAUSE = "safety_pause"
    TIMEOUT = "timeout"
    INVENTORY_MISMATCH = "inventory_mismatch"
    PHASE_IMPOSSIBLE = "phase_impossible"
    BRIDGE_ERROR = "bridge_error"
    UNKNOWN = "unknown"


@dataclass
class PhaseResult:
    """Record of what happened during a single phase attempt."""

    phase: SurvivalPhase
    success: bool
    actions_attempted: int = 0
    actions_succeeded: int = 0
    failure_category: FailureCategory | None = None
    failure_message: str = ""
    elapsed_ms: float = 0.0
    action_log: list[dict[str, Any]] = field(default_factory=list)

    def record_action(
        self,
        action: str,
        params: dict[str, Any],
        success: bool,
        result: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.actions_attempted += 1
        if success:
            self.actions_succeeded += 1
        self.action_log.append(
            {
                "action": action,
                "params": params,
                "success": success,
                "result": result,
                **({"detail": detail} if detail else {}),
            }
        )

    def mark_failure(self, category: FailureCategory, message: str = "") -> None:
        self.success = False
        self.failure_category = category
        self.failure_message = message


@dataclass
class InventoryGoal:
    """A required item in the terminal inventory."""

    item: str
    min_count: int = 1


# Terminal inventory goals for iron survival
IRON_SURVIVAL_GOALS: list[InventoryGoal] = [
    InventoryGoal("iron_pickaxe", 1),
    InventoryGoal("iron_sword", 1),
    InventoryGoal("iron_chestplate", 1),
]

# Recommended support items (not required for success)
IRON_SURVIVAL_SUPPORT: list[InventoryGoal] = [
    InventoryGoal("crafting_table", 1),
    InventoryGoal("furnace", 1),
    InventoryGoal("stone_pickaxe", 1),
]


@dataclass
class RunReport:
    """Complete report of a survival iron run."""

    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    completed: bool = False
    current_phase: SurvivalPhase = SurvivalPhase.WOOD
    phase_results: list[PhaseResult] = field(default_factory=list)
    final_inventory: dict[str, int] = field(default_factory=dict)
    deaths: int = 0
    status_snapshots: list[dict[str, Any]] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        if self.end_time > 0:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    def phase_attempts(self, phase: SurvivalPhase) -> int:
        return sum(1 for pr in self.phase_results if pr.phase == phase)

    def phase_failures(self, phase: SurvivalPhase) -> list[PhaseResult]:
        return [pr for pr in self.phase_results if pr.phase == phase and not pr.success]

    def summary(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "total_phases": len(self.phase_results),
            "total_actions": sum(pr.actions_attempted for pr in self.phase_results),
            "deaths": self.deaths,
            "final_inventory": dict(self.final_inventory),
            "phase_summary": [
                {
                    "phase": pr.phase.value,
                    "success": pr.success,
                    "actions": pr.actions_succeeded,
                    "failure": pr.failure_category.value if pr.failure_category else None,
                }
                for pr in self.phase_results
            ],
        }
