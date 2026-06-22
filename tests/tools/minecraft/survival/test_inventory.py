"""Tests for survival_inventory.py — alias normalization and goal checking."""

from animetta.tools.minecraft.survival.inventory import (
    PHASE_COMPLETION,
    PHASE_REQUIREMENTS,
    all_goals_satisfied,
    check_phase_inventory,
    find_fuel_item,
    goal_satisfied,
    missing_materials,
    normalize_inventory,
    normalize_item_name,
)
from animetta.tools.minecraft.survival.models import InventoryGoal


class TestNormalizeItemName:
    def test_canonical_passthrough(self):
        assert normalize_item_name("oak_log") == "oak_log"
        assert normalize_item_name("iron_pickaxe") == "iron_pickaxe"

    def test_wood_aliases(self):
        assert normalize_item_name("spruce_log") == "oak_log"
        assert normalize_item_name("birch_log") == "oak_log"
        assert normalize_item_name("log") == "oak_log"
        assert normalize_item_name("wood") == "oak_log"

    def test_planks_aliases(self):
        assert normalize_item_name("planks") == "oak_planks"
        assert normalize_item_name("wooden_plank") == "oak_planks"

    def test_sticks_alias(self):
        assert normalize_item_name("sticks") == "stick"

    def test_cobble_alias(self):
        assert normalize_item_name("cobble") == "cobblestone"

    def test_coal_alias(self):
        assert normalize_item_name("coal_ore") == "coal"

    def test_unknown_passthrough(self):
        assert normalize_item_name("diamond_sword") == "diamond_sword"

    def test_station_aliases(self):
        assert normalize_item_name("workbench") == "crafting_table"


class TestNormalizeInventory:
    def test_merge_same_items(self):
        raw = {"oak_log": 2, "spruce_log": 3}
        result = normalize_inventory(raw)
        assert result["oak_log"] == 5

    def test_merge_planks(self):
        raw = {"oak_planks": 2, "planks": 1}
        result = normalize_inventory(raw)
        assert result["oak_planks"] == 3

    def test_unknown_items_preserved(self):
        raw = {"diamond": 1}
        result = normalize_inventory(raw)
        assert result["diamond"] == 1

    def test_empty_inventory(self):
        assert normalize_inventory({}) == {}


class TestGoalSatisfied:
    def test_met(self):
        inv = {"iron_pickaxe": 2}
        assert goal_satisfied(inv, InventoryGoal("iron_pickaxe", 1)) is True

    def test_exact_count(self):
        inv = {"iron_pickaxe": 1}
        assert goal_satisfied(inv, InventoryGoal("iron_pickaxe", 1)) is True

    def test_not_met(self):
        inv = {"iron_pickaxe": 0}
        assert goal_satisfied(inv, InventoryGoal("iron_pickaxe", 1)) is False

    def test_missing_item(self):
        inv = {}
        assert goal_satisfied(inv, InventoryGoal("iron_pickaxe", 1)) is False


class TestAllGoalsSatisfied:
    def test_all_met(self):
        inv = {"iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1}
        goals = [
            InventoryGoal("iron_pickaxe"),
            InventoryGoal("iron_sword"),
            InventoryGoal("iron_chestplate"),
        ]
        assert all_goals_satisfied(inv, goals) is True

    def test_one_missing(self):
        inv = {"iron_pickaxe": 1, "iron_sword": 1}
        goals = [
            InventoryGoal("iron_pickaxe"),
            InventoryGoal("iron_sword"),
            InventoryGoal("iron_chestplate"),
        ]
        assert all_goals_satisfied(inv, goals) is False

    def test_empty_goals(self):
        assert all_goals_satisfied({}, []) is True


class TestMissingMaterials:
    def test_nothing_missing(self):
        inv = {"oak_planks": 8, "stick": 4}
        req = {"oak_planks": 4, "stick": 2}
        assert missing_materials(inv, req) == {}

    def test_one_missing(self):
        inv = {"oak_planks": 2}
        req = {"oak_planks": 4}
        m = missing_materials(inv, req)
        assert m == {"oak_planks": 2}

    def test_multiple_missing(self):
        inv = {}
        req = {"oak_planks": 4, "stick": 2}
        m = missing_materials(inv, req)
        assert m == {"oak_planks": 4, "stick": 2}


class TestCheckPhaseInventory:
    def test_satisfied(self):
        inv = {"oak_planks": 4}
        ok, missing = check_phase_inventory(inv, {"oak_planks": 4})
        assert ok is True
        assert missing == {}

    def test_not_satisfied(self):
        inv = {"oak_planks": 2}
        ok, missing = check_phase_inventory(inv, {"oak_planks": 4})
        assert ok is False
        assert missing == {"oak_planks": 2}


class TestPhaseData:
    def test_all_phases_have_requirements(self):
        for phase_name in [
            "crafting_table", "wooden_pickaxe", "cobblestone",
            "stone_kit", "fuel", "iron_ore", "smelt_iron", "iron_gear",
        ]:
            assert phase_name in PHASE_REQUIREMENTS, f"Missing requirements for {phase_name}"

    def test_all_phases_have_completion(self):
        for phase_name in [
            "wood", "crafting_table", "wooden_pickaxe", "cobblestone",
            "stone_kit", "fuel", "iron_ore", "smelt_iron", "iron_gear",
        ]:
            assert phase_name in PHASE_COMPLETION, f"Missing completion for {phase_name}"

    def test_iron_gear_completion_needs_three_items(self):
        gear = PHASE_COMPLETION["iron_gear"]
        assert gear["iron_pickaxe"] >= 1
        assert gear["iron_sword"] >= 1
        assert gear["iron_chestplate"] >= 1


class TestFindFuelItem:
    def test_coal_preferred(self):
        inv = {"coal": 3, "oak_log": 5}
        assert find_fuel_item(inv) == "coal"

    def test_charcoal_fallback(self):
        inv = {"charcoal": 2}
        assert find_fuel_item(inv) == "charcoal"

    def test_log_fallback(self):
        inv = {"oak_log": 5}
        assert find_fuel_item(inv) == "oak_log"

    def test_planks_fallback(self):
        inv = {"oak_planks": 8}
        assert find_fuel_item(inv) == "oak_planks"

    def test_no_fuel(self):
        assert find_fuel_item({}) is None

    def test_stick_last_resort(self):
        inv = {"stick": 4}
        assert find_fuel_item(inv) == "stick"
