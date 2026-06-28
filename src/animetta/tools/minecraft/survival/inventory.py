"""Survival inventory helpers — alias normalization, goal satisfaction, missing materials."""

from __future__ import annotations

from .models import InventoryGoal

# Minecraft item name aliases → canonical name
# Covers common synonyms the bridge or status report might use.
ITEM_ALIASES: dict[str, str] = {
    # Wood variants
    "oak_log": "oak_log",
    "spruce_log": "oak_log",
    "birch_log": "oak_log",
    "jungle_log": "oak_log",
    "acacia_log": "oak_log",
    "dark_oak_log": "oak_log",
    "log": "oak_log",
    "wood": "oak_log",
    # Planks
    "oak_planks": "oak_planks",
    "spruce_planks": "oak_planks",
    "birch_planks": "oak_planks",
    "planks": "oak_planks",
    "wooden_plank": "oak_planks",
    # Sticks
    "stick": "stick",
    "sticks": "stick",
    # Cobblestone
    "cobblestone": "cobblestone",
    "cobble": "cobblestone",
    # Stone
    "stone": "stone",
    # Iron
    "raw_iron": "raw_iron",
    "iron_ore": "iron_ore",
    "iron_ingot": "iron_ingot",
    # Coal
    "coal": "coal",
    "coal_ore": "coal",
    # Charcoal
    "charcoal": "charcoal",
    # Fuel shortcuts
    "oak_plank": "oak_planks",
    "oak_log_fuel": "oak_log",
    # Tools
    "wooden_pickaxe": "wooden_pickaxe",
    "stone_pickaxe": "stone_pickaxe",
    "iron_pickaxe": "iron_pickaxe",
    "wooden_sword": "wooden_sword",
    "stone_sword": "stone_sword",
    "iron_sword": "iron_sword",
    # Armor
    "iron_chestplate": "iron_chestplate",
    # Station
    "crafting_table": "crafting_table",
    "workbench": "crafting_table",
    "furnace": "furnace",
}


def normalize_item_name(name: str) -> str:
    """Normalize an item name using known aliases."""
    return ITEM_ALIASES.get(name, name)


def normalize_inventory(raw: dict[str, int]) -> dict[str, int]:
    """Normalize and merge inventory counts by canonical item names."""
    result: dict[str, int] = {}
    for item, count in raw.items():
        canonical = normalize_item_name(item)
        result[canonical] = result.get(canonical, 0) + count
    return result


def goal_satisfied(inventory: dict[str, int], goal: InventoryGoal) -> bool:
    """Check if a single inventory goal is met."""
    return inventory.get(goal.item, 0) >= goal.min_count


def all_goals_satisfied(
    inventory: dict[str, int],
    goals: list[InventoryGoal],
) -> bool:
    """Check if all goals are met."""
    return all(goal_satisfied(inventory, g) for g in goals)


def missing_materials(
    inventory: dict[str, int],
    requirements: dict[str, int],
) -> dict[str, int]:
    """Return dict of item → count still needed (only items with deficit)."""
    missing: dict[str, int] = {}
    for item, needed in requirements.items():
        have = inventory.get(item, 0)
        if have < needed:
            missing[item] = needed - have
    return missing


def check_phase_inventory(
    inventory: dict[str, int],
    required_items: dict[str, int],
) -> tuple[bool, dict[str, int]]:
    """Check if inventory satisfies required items.

    Returns:
        (satisfied, missing_dict)
    """
    missing = missing_materials(inventory, required_items)
    return len(missing) == 0, missing


# Phase-specific inventory requirements (what you need BEFORE attempting the phase)
PHASE_REQUIREMENTS: dict[str, dict[str, int]] = {
    "crafting_table": {"oak_planks": 4},
    "wooden_pickaxe": {"oak_planks": 3, "stick": 2},
    "cobblestone": {},  # just mine stone
    "stone_kit": {
        "cobblestone": 11,  # 3 pickaxe + 2 sword + 8 furnace
        "stick": 3,  # 1 pickaxe + 1 sword
    },
    "fuel": {},  # just find coal
    "iron_ore": {},  # just mine
    "smelt_iron": {"raw_iron": 3, "coal": 1},  # minimum for 1 ingot set
    "iron_gear": {"iron_ingot": 12},  # pickaxe(3) + sword(2) + chestplate(7) = 12
}

# Phase completion inventory checks (what should be IN inventory AFTER phase)
PHASE_COMPLETION: dict[str, dict[str, int]] = {
    "wood": {"oak_log": 1},
    "crafting_table": {"crafting_table": 1},
    "wooden_pickaxe": {"wooden_pickaxe": 1},
    "cobblestone": {"cobblestone": 1},
    "stone_kit": {"stone_pickaxe": 1, "stone_sword": 1, "furnace": 1},
    "fuel": {"coal": 1},
    "iron_ore": {"raw_iron": 1},
    "smelt_iron": {"iron_ingot": 1},
    "iron_gear": {"iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1},
}


def find_fuel_item(inventory: dict[str, int]) -> str | None:
    """Find the best available fuel item in inventory, or None."""
    fuel_priority = ["coal", "charcoal", "oak_log", "oak_planks", "stick"]
    for fuel in fuel_priority:
        if inventory.get(fuel, 0) > 0:
            return fuel
    return None


# -- Item -> Mineable Block Mapping --

# Maps inventory item names to the Minecraft block that must be mined/collected
# to obtain them.  The runner sends these block names to the Node.js bot's
# collect action, which looks up blocks by name in mcData.blocksByName.
ITEM_TO_BLOCK = {
    # Ores -> their ore blocks (drop the raw item when mined)
    "raw_iron": "iron_ore",
    "raw_copper": "copper_ore",
    "raw_gold": "gold_ore",
    "diamond": "diamond_ore",
    "emerald": "emerald_ore",
    "lapis_lazuli": "lapis_ore",
    "redstone": "redstone_ore",
    # Coal can come from coal_ore or deepslate_coal_ore; use coal_ore
    "coal": "coal_ore",
    # Cobblestone comes from mining stone
    "cobblestone": "stone",
    # Wood comes from log blocks
    "oak_log": "oak_log",
    "spruce_log": "spruce_log",
    "birch_log": "birch_log",
}


def resolve_block_type(item_name):
    """Translate an inventory item name to the block type to mine.

    Returns the Minecraft block name (suitable for mcData.blocksByName),
    or None if the item cannot be obtained by mining a block.
    """
    return ITEM_TO_BLOCK.get(item_name)
