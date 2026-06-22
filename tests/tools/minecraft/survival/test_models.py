"""Tests for survival_models.py — domain models for the iron survival runner."""

from animetta.tools.minecraft.survival.models import (
    IRON_SURVIVAL_GOALS,
    IRON_SURVIVAL_SUPPORT,
    PHASE_ORDER,
    FailureCategory,
    InventoryGoal,
    PhaseResult,
    RunReport,
    SurvivalPhase,
)


class TestSurvivalPhase:
    def test_phase_order_is_complete(self):
        assert len(PHASE_ORDER) == 10
        assert PHASE_ORDER[0] == SurvivalPhase.WOOD
        assert PHASE_ORDER[-1] == SurvivalPhase.DONE

    def test_phase_enum_values(self):
        assert SurvivalPhase.WOOD.value == "wood"
        assert SurvivalPhase.IRON_GEAR.value == "iron_gear"
        assert SurvivalPhase.DONE.value == "done"


class TestFailureCategory:
    def test_all_categories_exist(self):
        cats = [
            FailureCategory.ACTION_FAILED,
            FailureCategory.RESOURCE_UNAVAILABLE,
            FailureCategory.SAFETY_PAUSE,
            FailureCategory.TIMEOUT,
            FailureCategory.INVENTORY_MISMATCH,
            FailureCategory.PHASE_IMPOSSIBLE,
            FailureCategory.BRIDGE_ERROR,
            FailureCategory.UNKNOWN,
        ]
        assert len(cats) == 8
        # Each has a distinct value
        values = [c.value for c in cats]
        assert len(set(values)) == 8


class TestPhaseResult:
    def test_create_defaults(self):
        pr = PhaseResult(phase=SurvivalPhase.WOOD, success=True)
        assert pr.phase == SurvivalPhase.WOOD
        assert pr.success is True
        assert pr.actions_attempted == 0
        assert pr.actions_succeeded == 0
        assert pr.failure_category is None
        assert pr.action_log == []

    def test_record_action_success(self):
        pr = PhaseResult(phase=SurvivalPhase.WOOD, success=True)
        pr.record_action("collect", {"block_type": "oak_log"}, True, "Collected 3 oak_log")
        assert pr.actions_attempted == 1
        assert pr.actions_succeeded == 1
        assert len(pr.action_log) == 1
        assert pr.action_log[0]["action"] == "collect"
        assert pr.action_log[0]["success"] is True

    def test_record_action_failure(self):
        pr = PhaseResult(phase=SurvivalPhase.WOOD, success=True)
        pr.record_action("collect", {"block_type": "oak_log"}, False, "No oak_log nearby")
        assert pr.actions_attempted == 1
        assert pr.actions_succeeded == 0
        assert pr.action_log[0]["success"] is False

    def test_mark_failure(self):
        pr = PhaseResult(phase=SurvivalPhase.IRON_ORE, success=True)
        pr.mark_failure(FailureCategory.SAFETY_PAUSE, "Health low")
        assert pr.success is False
        assert pr.failure_category == FailureCategory.SAFETY_PAUSE
        assert pr.failure_message == "Health low"

    def test_record_action_with_detail(self):
        pr = PhaseResult(phase=SurvivalPhase.COBBLESTONE, success=True)
        pr.record_action("mine", {"block_type": "stone"}, True, "Mined 1 stone", {"position": {"x": 1, "y": 2}})
        assert pr.action_log[0]["detail"] == {"position": {"x": 1, "y": 2}}


class TestInventoryGoal:
    def test_create_default(self):
        g = InventoryGoal(item="iron_pickaxe")
        assert g.item == "iron_pickaxe"
        assert g.min_count == 1

    def test_create_with_count(self):
        g = InventoryGoal(item="iron_ingot", min_count=12)
        assert g.min_count == 12


class TestIronSurvivalGoals:
    def test_goals_include_iron_gear(self):
        items = [g.item for g in IRON_SURVIVAL_GOALS]
        assert "iron_pickaxe" in items
        assert "iron_sword" in items
        assert "iron_chestplate" in items

    def test_support_includes_essentials(self):
        items = [g.item for g in IRON_SURVIVAL_SUPPORT]
        assert "crafting_table" in items
        assert "furnace" in items


class TestRunReport:
    def test_create_defaults(self):
        r = RunReport()
        assert r.completed is False
        assert r.current_phase == SurvivalPhase.WOOD
        assert r.phase_results == []
        assert r.final_inventory == {}
        assert r.deaths == 0

    def test_elapsed_seconds(self):
        r = RunReport(start_time=100.0, end_time=200.0)
        assert r.elapsed_seconds == 100.0

    def test_phase_attempts(self):
        r = RunReport()
        r.phase_results = [
            PhaseResult(phase=SurvivalPhase.WOOD, success=True),
            PhaseResult(phase=SurvivalPhase.WOOD, success=False),
            PhaseResult(phase=SurvivalPhase.COBBLESTONE, success=True),
        ]
        assert r.phase_attempts(SurvivalPhase.WOOD) == 2
        assert r.phase_attempts(SurvivalPhase.COBBLESTONE) == 1
        assert r.phase_attempts(SurvivalPhase.IRON_ORE) == 0

    def test_phase_failures(self):
        r = RunReport()
        r.phase_results = [
            PhaseResult(phase=SurvivalPhase.WOOD, success=True),
            PhaseResult(phase=SurvivalPhase.WOOD, success=False),
        ]
        failures = r.phase_failures(SurvivalPhase.WOOD)
        assert len(failures) == 1
        assert failures[0].success is False

    def test_summary(self):
        r = RunReport(start_time=100.0, end_time=200.0)
        r.phase_results = [
            PhaseResult(phase=SurvivalPhase.WOOD, success=True, actions_attempted=1, actions_succeeded=1),
        ]
        r.final_inventory = {"oak_log": 3}
        s = r.summary()
        assert s["completed"] is False
        assert s["elapsed_seconds"] == 100.0
        assert s["total_phases"] == 1
        assert s["total_actions"] == 1
        assert s["final_inventory"] == {"oak_log": 3}
