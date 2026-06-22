"""Tests for survival_recovery.py — recovery strategies and safety checks."""

from animetta.tools.minecraft.survival.models import SurvivalPhase
from animetta.tools.minecraft.survival.recovery import (
    PHASE_RECOVERY_MAP,
    RecoveryAction,
    _extract_error,
    check_safety,
    get_phase_recovery_actions,
    get_phase_retry_budget,
    map_collect_failure,
    map_craft_failure,
    map_smelt_failure,
)


class TestExtractError:
    def test_string_passthrough(self):
        msg, raw = _extract_error("some error")
        assert msg == "some error"
        assert raw == {}

    def test_dict_extracts_message(self):
        msg, raw = _extract_error({"message": "timed out", "code": "TIMEOUT"})
        assert msg == "timed out"
        assert raw["code"] == "TIMEOUT"

    def test_dict_no_message_key(self):
        msg, raw = _extract_error({"code": "X"})
        assert "code" in msg  # falls back to str(dict)


class TestMapCollectFailure:
    def test_unknown_block_aborts(self):
        plan = map_collect_failure("nonexistent_block", "Unknown block: nonexistent_block", SurvivalPhase.WOOD)
        assert plan.should_abort is True
        assert "nonexistent_block" in plan.abort_reason

    def test_not_found_retries(self):
        plan = map_collect_failure("oak_log", "No more oak_log nearby, collected 0", SurvivalPhase.WOOD)
        assert plan.should_abort is False
        assert len(plan.actions) == 1
        assert plan.actions[0].action == "collect"
        assert plan.actions[0].params["block_type"] == "oak_log"

    def test_timeout_retries(self):
        plan = map_collect_failure("stone", "Command timed out after 60s", SurvivalPhase.COBBLESTONE)
        assert plan.should_abort is False
        assert len(plan.actions) == 2
        assert plan.actions[0].action == "stop"
        assert plan.actions[1].action == "collect"

    def test_generic_retry(self):
        plan = map_collect_failure("coal", "Some random error", SurvivalPhase.FUEL)
        assert plan.should_abort is False
        assert len(plan.actions) == 1

    def test_structured_no_blocks_code(self):
        """Node.js sends {code: 'NO_BLOCKS', collected: 2}."""
        plan = map_collect_failure(
            "iron_ore",
            {"message": "no blocks found", "code": "NO_BLOCKS", "collected": 2},
            SurvivalPhase.IRON_ORE,
        )
        assert plan.should_abort is False
        assert len(plan.actions) == 1
        assert plan.actions[0].action == "collect"

    def test_structured_block_not_found_aborts(self):
        plan = map_collect_failure(
            "bedrock",
            {"message": "Unknown block type", "code": "BLOCK_NOT_FOUND"},
            SurvivalPhase.WOOD,
        )
        assert plan.should_abort is True

    def test_structured_timeout(self):
        plan = map_collect_failure(
            "stone",
            {"message": "action timed out", "code": "TIMEOUT"},
            SurvivalPhase.COBBLESTONE,
        )
        assert plan.should_abort is False
        assert plan.actions[0].action == "stop"

    def test_structured_reason_in_description(self):
        plan = map_collect_failure(
            "coal",
            {"message": "generic fail", "reason": "cave collapsed"},
            SurvivalPhase.FUEL,
        )
        assert "cave collapsed" in plan.actions[0].description


class TestMapCraftFailure:
    def test_unknown_item_aborts(self):
        plan = map_craft_failure("diamond_sword", "Item not found: diamond_sword")
        assert plan.should_abort is True

    def test_no_recipes_aborts(self):
        plan = map_craft_failure("bedrock", "No recipes found for: bedrock")
        assert plan.should_abort is True

    def test_missing_materials_gathers(self):
        plan = map_craft_failure("wooden_pickaxe", "missing materials")
        assert plan.should_abort is False
        # Without a missing dict, falls through to generic retry
        assert len(plan.actions) == 1
        assert plan.actions[0].action == "craft"

    def test_structured_missing_materials(self):
        """Node.js sends {message, missing: {oak_planks: 3}}."""
        plan = map_craft_failure(
            "wooden_pickaxe",
            {"message": "missing materials", "missing": {"oak_planks": 3, "stick": 2}},
        )
        assert plan.should_abort is False
        # Should have collect actions for each missing item + 1 craft retry
        assert len(plan.actions) == 3
        collect_actions = [a for a in plan.actions if a.action == "collect"]
        assert len(collect_actions) == 2
        collected_items = {a.params["block_type"] for a in collect_actions}
        assert collected_items == {"oak_planks", "stick"}

    def test_structured_needs_table(self):
        """Node.js sends {needsTable: true}."""
        plan = map_craft_failure(
            "stone_pickaxe",
            {"message": "no crafting table", "needsTable": True},
        )
        assert plan.should_abort is False
        assert len(plan.actions) == 2
        assert plan.actions[0].params["recipe"] == "crafting_table"
        assert plan.actions[1].params["recipe"] == "stone_pickaxe"

    def test_structured_no_recipe_aborts(self):
        plan = map_craft_failure(
            "bedrock",
            {"message": "No recipes found", "code": "NO_RECIPE"},
        )
        assert plan.should_abort is True


class TestMapSmeltFailure:
    def test_no_furnace_crafts_one(self):
        plan = map_smelt_failure("raw_iron", "coal", "No furnace nearby")
        assert plan.should_abort is False
        assert len(plan.actions) == 3
        assert plan.actions[0].action == "collect"
        assert plan.actions[1].action == "craft"
        assert plan.actions[2].action == "smelt"

    def test_unknown_fuel_switches(self):
        plan = map_smelt_failure("raw_iron", "lava_bucket", "Unknown fuel: lava_bucket")
        assert plan.should_abort is False
        assert len(plan.actions) == 1
        assert plan.actions[0].params["fuel"] == "coal"

    def test_unknown_fuel_coal_to_log(self):
        plan = map_smelt_failure("raw_iron", "coal", "Unknown fuel: coal")
        assert plan.actions[0].params["fuel"] == "oak_log"

    def test_generic_retry(self):
        plan = map_smelt_failure("raw_iron", "coal", "Some other error")
        assert plan.should_abort is False
        assert len(plan.actions) == 1

    def test_structured_no_furnace_code(self):
        plan = map_smelt_failure(
            "raw_iron", "coal",
            {"message": "No furnace found", "code": "NO_FURNACE"},
        )
        assert plan.should_abort is False
        assert len(plan.actions) == 3  # collect cobble, craft furnace, retry smelt

    def test_structured_unknown_fuel_code(self):
        plan = map_smelt_failure(
            "raw_iron", "lava_bucket",
            {"message": "fuel not recognized", "code": "UNKNOWN_FUEL", "reason": "lava_bucket not burnable"},
        )
        assert plan.actions[0].params["fuel"] == "coal"
        assert "lava_bucket not burnable" in plan.actions[0].description

    def test_structured_generic_with_reason(self):
        plan = map_smelt_failure(
            "raw_iron", "coal",
            {"message": "something else", "reason": "inventory full"},
        )
        assert "inventory full" in plan.actions[0].description


class TestCheckSafety:
    def test_healthy_inventory(self):
        status = {"health": 20, "food": 20, "nearby_entities": {"sheep": 1}}
        s = check_safety(status)
        assert s.safe is True

    def test_critical_health(self):
        status = {"health": 4, "food": 18, "nearby_entities": {}}
        s = check_safety(status)
        assert s.safe is False
        assert s.should_pause is True
        assert s.should_retreat is True

    def test_low_food(self):
        status = {"health": 14, "food": 4, "nearby_entities": {}}
        s = check_safety(status)
        assert s.safe is False
        assert s.should_pause is True

    def test_many_hostiles(self):
        status = {
            "health": 18,
            "food": 16,
            "nearby_entities": {"zombie": 2, "skeleton": 1, "spider": 1},
        }
        s = check_safety(status)
        assert s.safe is False
        assert s.should_retreat is True

    def test_few_hostiles_ok(self):
        status = {
            "health": 18,
            "food": 16,
            "nearby_entities": {"zombie": 1},
        }
        s = check_safety(status)
        assert s.safe is True

    def test_low_health_caution(self):
        status = {"health": 8, "food": 14, "nearby_entities": {}}
        s = check_safety(status)
        assert s.safe is True  # Not critical, but warns
        assert "caution" in s.reason.lower()


class TestPhaseRetryBudget:
    def test_wood_has_budget(self):
        assert get_phase_retry_budget(SurvivalPhase.WOOD) >= 2

    def test_iron_ore_has_budget(self):
        assert get_phase_retry_budget(SurvivalPhase.IRON_ORE) >= 2

    def test_unknown_phase_default(self):
        # Should not crash
        budget = get_phase_retry_budget(SurvivalPhase.DONE)
        assert budget >= 1


class TestPhaseRecoveryMap:
    def test_all_active_phases_covered(self):
        for phase in SurvivalPhase:
            if phase == SurvivalPhase.DONE:
                continue
            assert phase in PHASE_RECOVERY_MAP, f"Missing recovery for {phase}"

    def test_recovery_actions_are_recovery_actions(self):
        for phase, info in PHASE_RECOVERY_MAP.items():
            for action in info.get("fallback_actions", []):
                assert isinstance(action, RecoveryAction)

    def test_get_phase_recovery_actions(self):
        actions = get_phase_recovery_actions(SurvivalPhase.WOOD)
        assert len(actions) >= 1
        assert actions[0].action == "collect"
