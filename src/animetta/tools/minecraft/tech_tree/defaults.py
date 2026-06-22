"""Default Minecraft tech-tree phases and phase task templates."""

from __future__ import annotations

from typing import Any

from loguru import logger

from .models import TechTreeConfig, TechTreePhase

WOOD_PHASE = TechTreePhase(
    name="wood",
    time_budget_minutes=10,
    required_items={"wooden_pickaxe": 1, "wooden_sword": 1, "crafting_table": 1},
    skills_to_learn=["craft_wooden_pickaxe", "craft_wooden_sword", "place_crafting_table"],
    description=(
        "Gather wood, craft a crafting table, wooden pickaxe, and wooden sword. "
        "Establishes the basic toolchain for further progression."
    ),
)

STONE_PHASE = TechTreePhase(
    name="stone",
    time_budget_minutes=15,
    required_items={"stone_pickaxe": 1, "stone_sword": 1, "furnace": 1},
    skills_to_learn=["mine_cobblestone", "craft_furnace", "craft_stone_pickaxe", "craft_stone_sword"],
    description=(
        "Mine cobblestone, build a furnace, and upgrade to stone tools. "
        "Opens access to smelting and iron-tier resources."
    ),
)

IRON_PHASE = TechTreePhase(
    name="iron",
    time_budget_minutes=20,
    required_items={"iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1},
    skills_to_learn=[
        "mine_iron_ore",
        "smelt_iron_ingot",
        "craft_iron_pickaxe",
        "craft_iron_sword",
        "craft_iron_chestplate",
    ],
    description=(
        "Mine iron ore, smelt ingots, and craft iron tools plus armour. "
        "The longest phase - requires both mining depth and smelting time."
    ),
)

DIAMOND_PHASE = TechTreePhase(
    name="diamond",
    time_budget_minutes=15,
    required_items={"diamond_pickaxe": 1, "diamond_sword": 1},
    skills_to_learn=["mine_diamond_ore", "craft_diamond_pickaxe", "craft_diamond_sword"],
    description=(
        "Mine diamonds at deep Y-levels and craft diamond tools. "
        "Final tier - completes the tech tree."
    ),
)

_PREDEFINED_PHASES: list[TechTreePhase] = [
    WOOD_PHASE,
    STONE_PHASE,
    IRON_PHASE,
    DIAMOND_PHASE,
]


def create_default_tech_tree() -> TechTreeConfig:
    """Create the default wood -> stone -> iron -> diamond tech tree."""
    config = TechTreeConfig(phases=list(_PREDEFINED_PHASES), total_time_budget_minutes=60)
    warnings = config.validate()
    if warnings:
        for warning in warnings:
            logger.warning(f"[TechTree] Config warning: {warning}")
    logger.info(
        "[TechTree] Created default tech tree: "
        + f"{len(config.phases)} phases, {config.total_time_budget_minutes}min budget"
    )
    return config


def _phase_tasks(phase_name: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Return the ordered task list for *phase_name*."""
    if phase_name == "wood":
        return [
            ("collect_oak_log", "collect", {"block_type": "oak_log", "count": 4}),
            ("craft_oak_planks", "craft", {"recipe": "oak_planks", "count": 8}),
            ("craft_stick", "craft", {"recipe": "stick", "count": 4}),
            ("craft_crafting_table", "craft", {"recipe": "crafting_table", "count": 1}),
            ("craft_wooden_pickaxe", "craft", {"recipe": "wooden_pickaxe", "count": 1}),
            ("craft_wooden_sword", "craft", {"recipe": "wooden_sword", "count": 1}),
        ]
    if phase_name == "stone":
        return [
            ("mine_cobblestone", "mine", {"block_type": "stone", "count": 8}),
            ("craft_stone_pickaxe", "craft", {"recipe": "stone_pickaxe", "count": 1}),
            ("craft_stone_sword", "craft", {"recipe": "stone_sword", "count": 1}),
            ("craft_furnace", "craft", {"recipe": "furnace", "count": 1}),
        ]
    if phase_name == "iron":
        return [
            ("mine_iron_ore", "collect", {"block_type": "iron_ore", "count": 6}),
            ("smelt_iron_ingot", "craft", {"recipe": "iron_ingot", "count": 6}),
            ("craft_iron_pickaxe", "craft", {"recipe": "iron_pickaxe", "count": 1}),
            ("craft_iron_sword", "craft", {"recipe": "iron_sword", "count": 1}),
            ("craft_iron_chestplate", "craft", {"recipe": "iron_chestplate", "count": 1}),
        ]
    if phase_name == "diamond":
        return [
            ("mine_diamond_ore", "collect", {"block_type": "diamond_ore", "count": 3}),
            ("craft_diamond_pickaxe", "craft", {"recipe": "diamond_pickaxe", "count": 1}),
            ("craft_diamond_sword", "craft", {"recipe": "diamond_sword", "count": 1}),
        ]
    logger.warning(f"[TechTree] No task definition for phase '{phase_name}'")
    return []
