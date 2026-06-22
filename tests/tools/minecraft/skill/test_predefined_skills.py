"""
Tests for predefined skills — validates all 6 starter skills.

Covers:
- Structural validity (all steps pass validate_params)
- Step sequence correctness per skill
"""

from animetta.tools.minecraft.predefined_skills import get_predefined_skills
from animetta.tools.minecraft.skill_library import Skill

# ── Fixtures ──

def _all_skills() -> list[Skill]:
    return get_predefined_skills()


def _skill_by_id(skill_id: str) -> Skill:
    for s in _all_skills():
        if s.id == skill_id:
            return s
    raise KeyError(f"Skill '{skill_id}' not found in predefined skills")


# ── Tests ──


class TestAllPredefinedSkillsValid:
    """Every predefined skill must have structurally valid steps."""

    def test_all_predefined_skills_valid(self) -> None:
        """All 9 predefined skills pass validate_params() on every step."""
        skills = _all_skills()
        assert len(skills) == 9, f"Expected 9 predefined skills, got {len(skills)}"

        for skill in skills:
            assert skill.id, "Skill missing id"
            assert skill.name, f"Skill '{skill.id}' missing name"
            assert skill.steps, f"Skill '{skill.id}' has no steps"

            for i, step in enumerate(skill.steps):
                errors = step.validate_params()
                assert errors == [], (
                    f"Skill '{skill.id}' step {i} ({step.name}) has validation errors: {errors}"
                )

    def test_all_skills_have_categories(self) -> None:
        """Every predefined skill has a non-empty category."""
        for skill in _all_skills():
            assert skill.category, f"Skill '{skill.id}' missing category"

    def test_all_skills_have_tags(self) -> None:
        """Every predefined skill has at least one tag."""
        for skill in _all_skills():
            assert skill.tags, f"Skill '{skill.id}' has no tags"


class TestSurvivalFoodSteps:
    """survival_food skill step sequence."""

    def test_survival_food_steps(self) -> None:
        """Correct step sequence: check → goto → collect."""
        skill = _skill_by_id("survival_food")
        step_names = [s.name for s in skill.steps]
        assert step_names == ["check", "goto", "collect"]

    def test_survival_food_check_condition(self) -> None:
        skill = _skill_by_id("survival_food")
        assert skill.steps[0].params["condition"] == "food < 15"

    def test_survival_food_collect_type(self) -> None:
        skill = _skill_by_id("survival_food")
        collect_step = skill.steps[2]
        assert collect_step.params["block_type"] == "beef|pork|chicken"
        assert collect_step.params["count"] == 3

    def test_survival_food_preconditions(self) -> None:
        skill = _skill_by_id("survival_food")
        assert "food < 15" in skill.preconditions

    def test_survival_food_postconditions(self) -> None:
        skill = _skill_by_id("survival_food")
        assert "food > 15" in skill.postconditions


class TestSurvivalShelterSteps:
    """survival_shelter skill step sequence."""

    def test_survival_shelter_steps(self) -> None:
        """Correct step sequence: 2 checks → goto → 8 places."""
        skill = _skill_by_id("survival_shelter")
        step_names = [s.name for s in skill.steps]
        assert step_names[0] == "check"
        assert step_names[1] == "check"
        assert step_names[2] == "goto"
        assert all(n == "place" for n in step_names[3:])
        assert len(step_names) == 11  # 2 checks + 1 goto + 8 places

    def test_survival_shelter_preconditions(self) -> None:
        skill = _skill_by_id("survival_shelter")
        assert "is_night" in skill.preconditions
        assert "health > 6" in skill.preconditions

    def test_survival_shelter_uses_cobblestone_and_planks(self) -> None:
        skill = _skill_by_id("survival_shelter")
        place_steps = [s for s in skill.steps if s.name == "place"]
        block_types = {s.params["block_type"] for s in place_steps}
        assert "cobblestone" in block_types
        assert "oak_planks" in block_types


class TestCollectMineSteps:
    """collect_mine skill step sequence."""

    def test_collect_mine_steps(self) -> None:
        """Correct step sequence: check → goto → mine → collect."""
        skill = _skill_by_id("collect_mine")
        step_names = [s.name for s in skill.steps]
        assert step_names == ["check", "goto", "mine", "collect"]

    def test_collect_mine_check_condition(self) -> None:
        skill = _skill_by_id("collect_mine")
        assert skill.steps[0].params["condition"] == "has_pickaxe"

    def test_collect_mine_mine_block(self) -> None:
        skill = _skill_by_id("collect_mine")
        mine_step = skill.steps[2]
        assert mine_step.params["block_type"] == "stone|cobblestone"
        assert mine_step.params["count"] == 16

    def test_collect_mine_preconditions(self) -> None:
        skill = _skill_by_id("collect_mine")
        assert "has_pickaxe" in skill.preconditions


class TestCollectWoodSteps:
    """collect_wood skill step sequence."""

    def test_collect_wood_steps(self) -> None:
        """Correct step sequence: check → goto → mine → collect."""
        skill = _skill_by_id("collect_wood")
        step_names = [s.name for s in skill.steps]
        assert step_names == ["check", "goto", "mine", "collect"]

    def test_collect_wood_mine_block(self) -> None:
        skill = _skill_by_id("collect_wood")
        mine_step = skill.steps[2]
        assert mine_step.params["block_type"] == "oak_log"
        assert mine_step.params["count"] == 8

    def test_collect_wood_preconditions(self) -> None:
        skill = _skill_by_id("collect_wood")
        assert "health > 6" in skill.preconditions


class TestBuildHouseSteps:
    """build_house skill step sequence."""

    def test_build_house_steps(self) -> None:
        """Correct step sequence: 2 checks → goto → 75 places (5x5x3)."""
        skill = _skill_by_id("build_house")
        step_names = [s.name for s in skill.steps]
        assert step_names[0] == "check"
        assert step_names[1] == "check"
        assert step_names[2] == "goto"
        assert all(n == "place" for n in step_names[3:])
        # 5x5 foundation + 5x5 walls + 5x5 roof = 75 places
        assert len(step_names) == 78  # 2 checks + 1 goto + 75 places

    def test_build_house_preconditions(self) -> None:
        skill = _skill_by_id("build_house")
        assert "has_cobblestone >= 32" in skill.preconditions
        assert "has_oak_log >= 16" in skill.preconditions

    def test_build_house_uses_correct_blocks(self) -> None:
        skill = _skill_by_id("build_house")
        place_steps = [s for s in skill.steps if s.name == "place"]
        block_types = {s.params["block_type"] for s in place_steps}
        assert "cobblestone" in block_types
        assert "oak_planks" in block_types

    def test_build_house_foundation_y64(self) -> None:
        """Foundation layer at y=64."""
        skill = _skill_by_id("build_house")
        place_steps = [s for s in skill.steps if s.name == "place"]
        foundation = [s for s in place_steps if s.params["y"] == 64]
        assert len(foundation) == 25  # 5x5

    def test_build_house_walls_y65(self) -> None:
        """Wall layer at y=65."""
        skill = _skill_by_id("build_house")
        place_steps = [s for s in skill.steps if s.name == "place"]
        walls = [s for s in place_steps if s.params["y"] == 65]
        assert len(walls) == 25  # 5x5

    def test_build_house_roof_y66(self) -> None:
        """Roof layer at y=66."""
        skill = _skill_by_id("build_house")
        place_steps = [s for s in skill.steps if s.name == "place"]
        roof = [s for s in place_steps if s.params["y"] == 66]
        assert len(roof) == 25  # 5x5


class TestBuildWallSteps:
    """build_wall skill step sequence."""

    def test_build_wall_steps(self) -> None:
        """Correct step sequence: check → goto → 16 places."""
        skill = _skill_by_id("build_wall")
        step_names = [s.name for s in skill.steps]
        assert step_names[0] == "check"
        assert step_names[1] == "goto"
        assert all(n == "place" for n in step_names[2:])
        assert len(step_names) == 18  # 1 check + 1 goto + 16 places

    def test_build_wall_preconditions(self) -> None:
        skill = _skill_by_id("build_wall")
        assert "has_cobblestone >= 16" in skill.preconditions

    def test_build_wall_uses_cobblestone(self) -> None:
        skill = _skill_by_id("build_wall")
        place_steps = [s for s in skill.steps if s.name == "place"]
        for s in place_steps:
            assert s.params["block_type"] == "cobblestone"

    def test_build_wall_all_at_z0(self) -> None:
        """Wall is a straight line at z=0."""
        skill = _skill_by_id("build_wall")
        place_steps = [s for s in skill.steps if s.name == "place"]
        for s in place_steps:
            assert s.params["z"] == 0

    def test_build_wall_x_range(self) -> None:
        """Wall spans x=0..15."""
        skill = _skill_by_id("build_wall")
        place_steps = [s for s in skill.steps if s.name == "place"]
        x_values = sorted(s.params["x"] for s in place_steps)
        assert x_values == list(range(16))
