"""Tests for SkillValidator — schema, action, and simulation validation."""

from __future__ import annotations

from animetta.tools.minecraft.skill.library import Skill, SkillStep
from animetta.tools.minecraft.skill.validator import (
    CHECK_ACTION,
    CHECK_SCHEMA,
    CHECK_SIMULATION,
    SimulatedState,
    SkillValidator,
    ValidationResult,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_skill(
    id: str = "test_skill_001",
    name: str = "collect_wood",
    description: str = "Gather oak logs.",
    category: str = "collection",
    steps: list[SkillStep] | None = None,
    preconditions: list[str] | None = None,
    tags: list[str] | None = None,
) -> Skill:
    """Build a minimal valid Skill."""
    if steps is None:
        steps = [
            SkillStep(name="goto", params={"x": 100, "y": 64, "z": -200}),
            SkillStep(name="collect", params={"block_type": "oak_log", "count": 10}),
        ]
    return Skill(
        id=id,
        name=name,
        description=description,
        category=category,
        steps=steps,
        preconditions=preconditions or [],
        tags=tags or ["wood"],
    )


# ── ValidationResult ─────────────────────────────────────────────────────────


class TestValidationResult:
    """ValidationResult dataclass tests."""

    def test_defaults(self):
        result = ValidationResult(passed=True)
        assert result.passed is True
        assert result.checks == []
        assert result.failures == []
        assert result.warnings == []

    def test_to_dict(self):
        result = ValidationResult(
            passed=False,
            checks=["schema"],
            failures=["missing id"],
            warnings=["empty description"],
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert d["checks"] == ["schema"]
        assert d["failures"] == ["missing id"]


# ── SimulatedState ───────────────────────────────────────────────────────────


class TestSimulatedState:
    """SimulatedState unit tests."""

    def test_default_state(self):
        state = SimulatedState()
        assert state.inventory == {}
        assert state.position == (0, 64, 0)
        assert state.health == 20.0
        assert state.food == 20

    def test_custom_state(self):
        state = SimulatedState(
            inventory={"oak_log": 10},
            position=(100, 64, -200),
            health=15.0,
            food=18,
        )
        assert state.inventory == {"oak_log": 10}
        assert state.position == (100, 64, -200)

    def test_has_item_true(self):
        state = SimulatedState(inventory={"oak_log": 5})
        assert state.has_item("oak_log", 3) is True

    def test_has_item_false_insufficient(self):
        state = SimulatedState(inventory={"oak_log": 2})
        assert state.has_item("oak_log", 5) is False

    def test_has_item_missing(self):
        state = SimulatedState()
        assert state.has_item("diamond", 1) is False

    def test_snapshot(self):
        state = SimulatedState(inventory={"stone": 64}, health=18.0)
        snap = state.snapshot()
        assert snap["health"] == 18.0
        assert snap["inventory"] == {"stone": 64}


class TestSimulatedStateCanExecute:
    """SimulatedState.can_execute() tests."""

    def test_goto_always_passes(self):
        state = SimulatedState()
        step = SkillStep(name="goto", params={"x": 10, "y": 64, "z": 5})
        ok, reason = state.can_execute(step)
        assert ok is True
        assert reason is None

    def test_collect_always_passes(self):
        state = SimulatedState()
        step = SkillStep(name="collect", params={"block_type": "oak_log", "count": 5})
        ok, reason = state.can_execute(step)
        assert ok is True

    def test_place_with_item_passes(self):
        state = SimulatedState(inventory={"cobblestone": 10})
        step = SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 63, "z": 0})
        ok, reason = state.can_execute(step)
        assert ok is True

    def test_place_without_item_fails(self):
        state = SimulatedState(inventory={})
        step = SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 63, "z": 0})
        ok, reason = state.can_execute(step)
        assert ok is False
        assert "not in simulated inventory" in reason

    def test_craft_with_materials_passes(self):
        state = SimulatedState(inventory={"oak_log": 3})
        step = SkillStep(name="craft", params={"recipe": "oak_planks", "count": 12})
        ok, reason = state.can_execute(step)
        assert ok is True

    def test_craft_without_materials_fails(self):
        state = SimulatedState(inventory={})
        step = SkillStep(name="craft", params={"recipe": "oak_planks", "count": 12})
        ok, reason = state.can_execute(step)
        assert ok is False
        assert "missing ingredients" in reason.lower()

    def test_low_health_blocks(self):
        state = SimulatedState(health=1.0)
        step = SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0})
        ok, reason = state.can_execute(step)
        assert ok is False
        assert "Health too low" in reason

    def test_low_food_blocks(self):
        state = SimulatedState(food=2)
        step = SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0})
        ok, reason = state.can_execute(step)
        assert ok is False
        assert "Food too low" in reason


class TestSimulatedStateApplyStep:
    """SimulatedState.apply_step() tests."""

    def test_goto_updates_position(self):
        state = SimulatedState()
        step = SkillStep(name="goto", params={"x": 100, "y": 70, "z": -50})
        state.apply_step(step)
        assert state.position == (100, 70, -50)

    def test_collect_adds_to_inventory(self):
        state = SimulatedState()
        step = SkillStep(name="collect", params={"block_type": "oak_log", "count": 5})
        state.apply_step(step)
        assert state.inventory["oak_log"] == 5

    def test_mine_adds_to_inventory(self):
        state = SimulatedState(inventory={"cobblestone": 3})
        step = SkillStep(name="mine", params={"block_type": "cobblestone", "count": 10})
        state.apply_step(step)
        assert state.inventory["cobblestone"] == 13

    def test_place_removes_from_inventory(self):
        state = SimulatedState(inventory={"cobblestone": 9})
        step = SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 63, "z": 0, "count": 1})
        state.apply_step(step)
        assert state.inventory["cobblestone"] == 8

    def test_place_does_not_go_negative(self):
        state = SimulatedState(inventory={"cobblestone": 0})
        step = SkillStep(name="place", params={"block_type": "cobblestone", "count": 5})
        state.apply_step(step)
        assert state.inventory["cobblestone"] == 0

    def test_craft_adds_output(self):
        state = SimulatedState(inventory={"oak_log": 3})
        step = SkillStep(name="craft", params={"recipe": "oak_planks", "count": 4})
        state.apply_step(step)
        assert state.inventory["oak_planks"] == 4

    def test_unknown_step_no_change(self):
        state = SimulatedState(inventory={"stone": 10})
        step = SkillStep(name="chat", params={"message": "hello"})
        state.apply_step(step)
        assert state.inventory == {"stone": 10}
        assert state.position == (0, 64, 0)


# ── SkillValidator — Schema ─────────────────────────────────────────────────


class TestSchemaValidation:
    """Phase 1: Schema validation."""

    def test_valid_skill_passes_schema(self):
        validator = SkillValidator()
        skill = _make_skill()
        result = ValidationResult(passed=True)
        validator._check_schema(skill, result)
        assert CHECK_SCHEMA in result.checks
        assert len(result.failures) == 0

    def test_missing_id_fails(self):
        validator = SkillValidator()
        skill = _make_skill(id="")
        result = ValidationResult(passed=True)
        validator._check_schema(skill, result)
        assert any("id" in f.lower() for f in result.failures)

    def test_missing_name_fails(self):
        validator = SkillValidator()
        skill = _make_skill(name="")
        result = ValidationResult(passed=True)
        validator._check_schema(skill, result)
        assert any("name" in f.lower() for f in result.failures)

    def test_empty_steps_fails(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[])
        result = ValidationResult(passed=True)
        validator._check_schema(skill, result)
        assert any("steps" in f.lower() for f in result.failures)

    def test_step_with_empty_name_fails(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[SkillStep(name="", params={})])
        result = ValidationResult(passed=True)
        validator._check_schema(skill, result)
        assert any("empty" in f.lower() and "name" in f.lower() for f in result.failures)

    def test_missing_description_warns(self):
        validator = SkillValidator()
        skill = _make_skill(description="")
        result = ValidationResult(passed=True)
        validator._check_schema(skill, result)
        assert len(result.failures) == 0
        assert any("description" in w.lower() for w in result.warnings)

    def test_missing_category_warns(self):
        validator = SkillValidator()
        skill = _make_skill(category="")
        result = ValidationResult(passed=True)
        validator._check_schema(skill, result)
        assert any("category" in w.lower() for w in result.warnings)


# ── SkillValidator — Action ─────────────────────────────────────────────────


class TestActionValidation:
    """Phase 2: Action validation."""

    def test_known_actions_pass(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="collect", params={"block_type": "oak_log", "count": 5}),
            SkillStep(name="mine", params={"block_type": "stone", "count": 3}),
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 63, "z": 0}),
        ])
        result = ValidationResult(passed=True)
        validator._check_actions(skill, result)
        assert CHECK_ACTION in result.checks
        assert len(result.failures) == 0

    def test_unknown_action_fails(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="fly_to_moon", params={}),
        ])
        result = ValidationResult(passed=True)
        validator._check_actions(skill, result)
        assert any("fly_to_moon" in f for f in result.failures)

    def test_mixed_valid_and_invalid(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="teleport", params={}),
        ])
        result = ValidationResult(passed=True)
        validator._check_actions(skill, result)
        assert any("teleport" in f for f in result.failures)
        # goto should not produce a failure
        assert not any("goto" in f for f in result.failures)


# ── SkillValidator — Simulation ─────────────────────────────────────────────


class TestSimulation:
    """Phase 3: Simulation validation."""

    def test_simulation_passes_with_valid_steps(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="goto", params={"x": 100, "y": 64, "z": -200}),
            SkillStep(name="collect", params={"block_type": "oak_log", "count": 5}),
        ])
        state = SimulatedState()
        result = ValidationResult(passed=True)
        validator._simulate(skill, state, result)
        assert CHECK_SIMULATION in result.checks
        assert len(result.failures) == 0

    def test_simulation_fails_on_low_health(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
        ])
        state = SimulatedState(health=1.0)
        result = ValidationResult(passed=True)
        validator._simulate(skill, state, result)
        assert any("Health too low" in f for f in result.failures)

    def test_simulation_fails_on_missing_place_item(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 63, "z": 0}),
        ])
        state = SimulatedState(inventory={})
        result = ValidationResult(passed=True)
        validator._simulate(skill, state, result)
        assert any("Cannot place" in f for f in result.failures)

    def test_simulation_advances_state(self):
        """After collecting, the simulated inventory should reflect the gain."""
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="collect", params={"block_type": "oak_log", "count": 10}),
            SkillStep(name="craft", params={"recipe": "oak_planks", "count": 4}),
        ])
        state = SimulatedState(inventory={})
        result = ValidationResult(passed=True)
        validator._simulate(skill, state, result)
        # collect adds 10 oak_log, then craft should pass (inventory non-empty)
        assert len(result.failures) == 0
        assert state.inventory.get("oak_log", 0) == 10

    def test_simulation_stops_on_first_failure(self):
        """Simulation should hard-stop at the first blocking failure."""
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 63, "z": 0}),
            SkillStep(name="goto", params={"x": 10, "y": 64, "z": 10}),
        ])
        state = SimulatedState(inventory={})
        result = ValidationResult(passed=True)
        validator._simulate(skill, state, result)
        # Only the first step should fail; second should not be reached
        assert len(result.failures) == 1
        assert "step 0" in result.failures[0]


# ── SkillValidator.validate (integration) ────────────────────────────────────


class TestValidateIntegration:
    """Full validate() pipeline tests."""

    def test_valid_skill_passes_all_checks(self):
        validator = SkillValidator()
        skill = _make_skill()
        result = validator.validate(skill)
        assert result.passed is True
        assert CHECK_SCHEMA in result.checks
        assert CHECK_ACTION in result.checks
        assert CHECK_SIMULATION in result.checks
        assert len(result.failures) == 0

    def test_schema_failure_skips_simulation(self):
        """When schema fails, simulation should be skipped."""
        validator = SkillValidator()
        skill = _make_skill(id="")
        result = validator.validate(skill)
        assert result.passed is False
        assert CHECK_SIMULATION not in result.checks

    def test_action_failure_skips_simulation(self):
        """When action check fails, simulation should be skipped."""
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="fly", params={}),
        ])
        result = validator.validate(skill)
        assert result.passed is False
        assert CHECK_SIMULATION not in result.checks

    def test_simulation_failure_with_context(self):
        """Simulation uses context to initialise state."""
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 63, "z": 0}),
        ])
        context = {"inventory": {"cobblestone": 20}, "health": 20.0, "food": 20}
        result = validator.validate(skill, context=context)
        assert result.passed is True
        assert CHECK_SIMULATION in result.checks

    def test_simulation_failure_without_enough_items(self):
        validator = SkillValidator()
        skill = _make_skill(steps=[
            SkillStep(name="place", params={"block_type": "diamond_block", "x": 0, "y": 63, "z": 0}),
        ])
        context = {"inventory": {"cobblestone": 20}}
        result = validator.validate(skill, context=context)
        assert result.passed is False

    def test_to_dict_roundtrip(self):
        validator = SkillValidator()
        skill = _make_skill()
        result = validator.validate(skill)
        d = result.to_dict()
        assert isinstance(d["passed"], bool)
        assert isinstance(d["checks"], list)
        assert isinstance(d["failures"], list)


# ── VALID_ACTIONS coverage ───────────────────────────────────────────────────


class TestValidActions:
    """VALID_ACTIONS set coverage."""

    def test_contains_step_types(self):
        from animetta.tools.minecraft.skill.validator import VALID_ACTIONS
        for step_type in ("goto", "collect", "mine", "place", "craft", "chat", "check", "wait"):
            assert step_type in VALID_ACTIONS

    def test_contains_available_tools(self):
        from animetta.tools.minecraft.skill.validator import VALID_ACTIONS
        # At minimum, goto, collect, mine, place, attack, chat should be there
        assert "attack" in VALID_ACTIONS
        assert "chat" in VALID_ACTIONS
