"""Survival recovery strategies and safety checks.

Maps action failures to recovery plans and provides safety gating
for high-risk phases like mining.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .survival_models import SurvivalPhase

# -- Recovery Actions --

@dataclass
class RecoveryAction:
    """A single recovery step to try after a failure."""

    action: str
    params: dict[str, Any]
    description: str
    timeout: float = 60.0


@dataclass
class RecoveryPlan:
    """Ordered list of recovery actions for a failed phase action."""

    actions: list[RecoveryAction] = field(default_factory=list)
    should_advance_phase: bool = False
    should_abort: bool = False
    abort_reason: str = ""


# -- Error Normalization --

def _extract_error(error: str | dict) -> tuple[str, dict]:
    """Normalize an error value into (message, raw_dict).

    Node.js handlers return structured dicts like
    ``{"message": "...", "code": "...", "collected": N, ...}``.
    This helper extracts the human-readable message and the full dict
    so recovery functions can use both.
    """
    if isinstance(error, dict):
        msg = error.get("message", str(error))
        return msg, error
    return str(error), {}


# -- Failure -> Recovery Mapping --

def map_collect_failure(
    block_type: str,
    error: str | dict,
    phase: SurvivalPhase,
) -> RecoveryPlan:
    """Map a failed collect/mine action to a recovery plan.

    Uses structured fields from Node.js when available:
    - ``code``: e.g. "NO_BLOCKS", "TIMEOUT", "BLOCK_NOT_FOUND"
    - ``collected``: how many were gathered before failure
    - ``explored``: how many chunks were searched
    - ``reason``: human-readable detail
    """
    msg, err = _extract_error(error)
    code = err.get("code", "")
    collected = err.get("collected", 0)
    reason = err.get("reason", "")

    if code == "BLOCK_NOT_FOUND" or "Unknown block" in msg:
        return RecoveryPlan(should_abort=True, abort_reason=f"Unknown block type: {block_type}")

    if code == "NO_BLOCKS" or "no more" in msg.lower() or "nearby" in msg.lower():
        # If we collected some, reduce the remaining count
        remaining = max(1, 1 - collected) if collected else 1
        return RecoveryPlan(
            actions=[
                RecoveryAction(
                    action="collect",
                    params={"block_type": block_type, "count": remaining},
                    description=f"Retry collect {block_type} with exploration" + (f" ({reason})" if reason else ""),
                    timeout=90.0,
                ),
            ]
        )

    if code == "TIMEOUT" or "timed out" in msg.lower():
        return RecoveryPlan(
            actions=[
                RecoveryAction(
                    action="stop",
                    params={},
                    description="Stop stuck action",
                ),
                RecoveryAction(
                    action="collect",
                    params={"block_type": block_type, "count": 1},
                    description=f"Retry collect {block_type} after timeout",
                    timeout=90.0,
                ),
            ]
        )

    return RecoveryPlan(
        actions=[
            RecoveryAction(
                action="collect",
                params={"block_type": block_type, "count": 1},
                description=f"Generic retry for {block_type}" + (f" ({reason})" if reason else ""),
                timeout=90.0,
            ),
        ]
    )


def map_craft_failure(
    recipe: str,
    error: str | dict,
) -> RecoveryPlan:
    """Map a failed craft action to a recovery plan.

    Uses structured fields from Node.js when available:
    - ``missing``: dict of item -> count needed (direct from Node.js)
    - ``needsTable``: whether a crafting table is required
    - ``code``: e.g. "MISSING_MATERIALS", "NO_CRAFTING_TABLE"
    """
    msg, err = _extract_error(error)
    missing = err.get("missing") or None
    needs_table = err.get("needsTable", False)
    code = err.get("code", "")

    if code == "NO_RECIPE" or "Item not found" in msg or "No recipes" in msg:
        return RecoveryPlan(should_abort=True, abort_reason=f"Cannot craft {recipe}: {msg}")

    if code == "NO_CRAFTING_TABLE" or needs_table:
        return RecoveryPlan(
            actions=[
                RecoveryAction(
                    action="craft",
                    params={"recipe": "crafting_table", "count": 1},
                    description="Craft crafting table first",
                ),
                RecoveryAction(
                    action="craft",
                    params={"recipe": recipe, "count": 1},
                    description=f"Retry craft {recipe}",
                ),
            ]
        )

    if (code == "MISSING_MATERIALS" or "missing materials" in msg.lower() or missing) and missing:
        # Node.js sent structured missing dict — build collect actions for each
        actions: list[RecoveryAction] = []
        for item, count in missing.items():
            actions.append(
                RecoveryAction(
                    action="collect",
                    params={"block_type": item, "count": count},
                    description=f"Collect missing {item} for {recipe}",
                    timeout=90.0,
                )
            )
        actions.append(
            RecoveryAction(
                action="craft",
                params={"recipe": recipe, "count": 1},
                description=f"Retry craft {recipe}",
            )
        )
        return RecoveryPlan(actions=actions)

    return RecoveryPlan(
        actions=[
            RecoveryAction(
                action="craft",
                params={"recipe": recipe, "count": 1},
                description=f"Generic retry craft {recipe}",
            ),
        ]
    )


def map_smelt_failure(
    item: str,
    fuel: str,
    error: str | dict,
) -> RecoveryPlan:
    """Map a failed smelt action to a recovery plan.

    Uses structured fields from Node.js when available:
    - ``code``: e.g. "NO_FURNACE", "UNKNOWN_FUEL"
    - ``reason``: human-readable detail
    """
    msg, err = _extract_error(error)
    code = err.get("code", "")
    reason = err.get("reason", "")

    if code == "NO_FURNACE" or "No furnace" in msg:
        return RecoveryPlan(
            actions=[
                RecoveryAction(
                    action="collect",
                    params={"block_type": "cobblestone", "count": 8},
                    description="Collect cobblestone for furnace",
                    timeout=90.0,
                ),
                RecoveryAction(
                    action="craft",
                    params={"recipe": "furnace", "count": 1},
                    description="Craft furnace",
                ),
                RecoveryAction(
                    action="smelt",
                    params={"item": item, "fuel": fuel, "count": 1},
                    description=f"Retry smelt {item}",
                ),
            ]
        )

    if code == "UNKNOWN_FUEL" or "unknown fuel" in msg.lower():
        result_fuel = "coal" if fuel != "coal" else "oak_log"
        return RecoveryPlan(
            actions=[
                RecoveryAction(
                    action="smelt",
                    params={"item": item, "fuel": result_fuel, "count": 1},
                    description=f"Retry smelt with {result_fuel} instead of {fuel}" + (f" ({reason})" if reason else ""),
                ),
            ]
        )

    return RecoveryPlan(
        actions=[
            RecoveryAction(
                action="smelt",
                params={"item": item, "fuel": fuel, "count": 1},
                description=f"Generic retry smelt {item}" + (f" ({reason})" if reason else ""),
            ),
        ]
    )


# -- Phase-Level Recovery --

PHASE_RECOVERY_MAP: dict[SurvivalPhase, dict[str, Any]] = {
    SurvivalPhase.WOOD: {
        "fallback_actions": [
            RecoveryAction("collect", {"block_type": "oak_log", "count": 3}, "Collect 3 logs with exploration", 120.0),
        ],
        "max_retries": 3,
    },
    SurvivalPhase.CRAFTING_TABLE: {
        "fallback_actions": [
            RecoveryAction("craft", {"recipe": "oak_planks", "count": 4}, "Craft planks first"),
            RecoveryAction("craft", {"recipe": "crafting_table", "count": 1}, "Then craft table"),
        ],
        "max_retries": 2,
    },
    SurvivalPhase.WOODEN_PICKAXE: {
        "fallback_actions": [
            RecoveryAction("craft", {"recipe": "oak_planks", "count": 2}, "Craft extra planks"),
            RecoveryAction("craft", {"recipe": "stick", "count": 2}, "Craft sticks"),
            RecoveryAction("craft", {"recipe": "wooden_pickaxe", "count": 1}, "Craft wooden pickaxe"),
        ],
        "max_retries": 2,
    },
    SurvivalPhase.COBBLESTONE: {
        "fallback_actions": [
            RecoveryAction("collect", {"block_type": "cobblestone", "count": 12}, "Collect 12 cobblestone", 120.0),
        ],
        "max_retries": 3,
    },
    SurvivalPhase.STONE_KIT: {
        "fallback_actions": [
            RecoveryAction("craft", {"recipe": "stone_pickaxe", "count": 1}, "Craft stone pickaxe"),
            RecoveryAction("craft", {"recipe": "stone_sword", "count": 1}, "Craft stone sword"),
            RecoveryAction("craft", {"recipe": "furnace", "count": 1}, "Craft furnace"),
        ],
        "max_retries": 2,
    },
    SurvivalPhase.FUEL: {
        "fallback_actions": [
            RecoveryAction("collect", {"block_type": "coal", "count": 3}, "Collect coal", 120.0),
        ],
        "max_retries": 3,
    },
    SurvivalPhase.IRON_ORE: {
        "fallback_actions": [
            RecoveryAction("collect", {"block_type": "raw_iron", "count": 3}, "Collect raw iron", 180.0),
        ],
        "max_retries": 3,
    },
SurvivalPhase.SMELT_IRON: {
        "fallback_actions": [
            RecoveryAction("smelt", {"item": "raw_iron", "fuel": "coal", "count": 3}, "Smelt 3 iron", 120.0),
        ],
        "max_retries": 2,
    },
    SurvivalPhase.IRON_GEAR: {
        "fallback_actions": [
            RecoveryAction("craft", {"recipe": "iron_pickaxe", "count": 1}, "Craft iron pickaxe"),
            RecoveryAction("craft", {"recipe": "iron_sword", "count": 1}, "Craft iron sword"),
            RecoveryAction("craft", {"recipe": "iron_chestplate", "count": 1}, "Craft iron chestplate"),
        ],
        "max_retries": 2,
    },
}


# -- Safety Checks --

@dataclass
class SafetyStatus:
    """Result of a safety check."""

    safe: bool
    reason: str = ""
    should_pause: bool = False
    should_retreat: bool = False


def check_safety(status_data: dict[str, Any]) -> SafetyStatus:
    """Evaluate world state for safety before high-risk mining phases."""
    health = status_data.get("health", 20)
    food = status_data.get("food", 20)
    entities = status_data.get("nearby_entities", {})

    if health <= 6:
        return SafetyStatus(
            safe=False,
            reason=f"Health critically low: {health}",
            should_pause=True,
            should_retreat=True,
        )

    if food <= 6:
        return SafetyStatus(
            safe=False,
            reason=f"Food critically low: {food}",
            should_pause=True,
        )

    hostiles = {"zombie", "skeleton", "spider", "creeper", "witch", "enderman", "wither_skeleton"}
    nearby_hostiles = sum(count for name, count in entities.items() if name.lower() in hostiles)
    if nearby_hostiles >= 3:
        return SafetyStatus(
            safe=False,
            reason=f"Multiple hostiles nearby: {nearby_hostiles}",
            should_pause=True,
            should_retreat=True,
        )

    if health <= 10:
        return SafetyStatus(
            safe=True,
            reason=f"Health low ({health}) - proceed with caution",
        )

    return SafetyStatus(safe=True)


def get_phase_retry_budget(phase: SurvivalPhase) -> int:
    """Get the max retry count for a phase."""
    info = PHASE_RECOVERY_MAP.get(phase, {})
    return info.get("max_retries", 2)


def get_phase_recovery_actions(phase: SurvivalPhase) -> list[RecoveryAction]:
    """Get the fallback recovery actions for a phase."""
    info = PHASE_RECOVERY_MAP.get(phase, {})
    return info.get("fallback_actions", [])
