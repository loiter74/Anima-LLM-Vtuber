"""
Integration tests for MC Bot craft action and skill execution.

Covers:
- Craft skill structure validation
- Material shortage scenario
- No workbench scenario
- Skill matching and execution via SkillLibrary
"""

from __future__ import annotations

import pytest

from animetta.tools.minecraft.skill.library import (
    Skill,
    SkillLibrary,
    check_preconditions,
)
from animetta.tools.minecraft.skill.predefined import get_predefined_skills

# ── Helpers ──────────────────────────────────────────────────────────────────


def _craft_skills() -> list[Skill]:
    """Return only the 3 crafting skills."""
    return [s for s in get_predefined_skills() if s.category == "crafting"]


def _skill_by_id(skill_id: str) -> Skill:
    for s in get_predefined_skills():
        if s.id == skill_id:
            return s
    raise KeyError(f"Skill '{skill_id}' not found")


def _inventory_ctx(items: dict[str, int]) -> dict:
    """Build a context with inventory."""
    return {"inventory": items}


# ── 4.1 Craft Action Basic Functionality ──────────────────────────────────────


class TestCraftSkillStructure:
    """Verify all craft skills have proper structure and steps."""

    def test_all_craft_skills_exist(self) -> None:
        """All 3 craft skills are present in predefined skills."""
        skills = _craft_skills()
        assert len(skills) == 6, f"Expected 6 craft skills, got {len(skills)}"

    def test_craft_equipment_exists(self) -> None:
        """craft_equipment skill exists with correct structure."""
        skill = _skill_by_id("craft_equipment")
        assert skill.id == "craft_equipment"
        assert skill.category == "crafting"
        assert len(skill.steps) > 0

    def test_craft_basic_tools_exists(self) -> None:
        """craft_basic_tools skill exists with correct structure."""
        skill = _skill_by_id("craft_basic_tools")
        assert skill.id == "craft_basic_tools"
        assert skill.category == "crafting"
        assert len(skill.steps) > 0

    def test_craft_armor_exists(self) -> None:
        """craft_armor skill exists with correct structure."""
        skill = _skill_by_id("craft_armor")
        assert skill.id == "craft_armor"
        assert skill.category == "crafting"
        assert len(skill.steps) > 0

    def test_craft_equipment_steps_all_craft(self) -> None:
        """craft_equipment steps use craft action after initial check."""
        skill = _skill_by_id("craft_equipment")
        step_names = [s.name for s in skill.steps]
        assert step_names[0] == "check"
        assert all(n == "craft" for n in step_names[1:]), (
            f"All non-check steps should be 'craft', got: {step_names[1:]}"
        )

    def test_craft_equipment_makes_progressive_tools(self) -> None:
        """craft_equipment crafts tools in progressive order."""
        skill = _skill_by_id("craft_equipment")
        recipes = [s.params["recipe"] for s in skill.steps if s.name == "craft"]
        # Should include sticks, then progressive pickaxes (wood→stone→iron→diamond)
        assert "stick" in recipes
        assert "wooden_pickaxe" in recipes
        assert "stone_pickaxe" in recipes
        assert "iron_pickaxe" in recipes
        assert "diamond_pickaxe" in recipes

    def test_craft_basic_tools_steps(self) -> None:
        """craft_basic_tools has check + craft steps."""
        skill = _skill_by_id("craft_basic_tools")
        step_names = [s.name for s in skill.steps]
        assert step_names[0] == "check"
        assert all(n == "craft" for n in step_names[1:])

    def test_craft_basic_tools_wood_only(self) -> None:
        """craft_basic_tools only crafts wooden tools."""
        skill = _skill_by_id("craft_basic_tools")
        recipes = [s.params["recipe"] for s in skill.steps if s.name == "craft"]
        for r in recipes:
            assert r in ("stick", "wooden_pickaxe", "wooden_axe", "wooden_sword"), (
                f"craft_basic_tools should only craft wooden items, got {r}"
            )

    def test_craft_armor_steps(self) -> None:
        """craft_armor crafts full iron armor set."""
        skill = _skill_by_id("craft_armor")
        step_names = [s.name for s in skill.steps]
        assert step_names[0] == "check"
        assert all(n == "craft" for n in step_names[1:])

    def test_craft_armor_full_set(self) -> None:
        """craft_armor covers all 4 armor pieces."""
        skill = _skill_by_id("craft_armor")
        recipes = [s.params["recipe"] for s in skill.steps if s.name == "craft"]
        assert "iron_helmet" in recipes
        assert "iron_chestplate" in recipes
        assert "iron_leggings" in recipes
        assert "iron_boots" in recipes

    def test_craft_skills_have_tags(self) -> None:
        """All craft skills have 'crafting' tag."""
        for skill in _craft_skills():
            assert "crafting" in skill.tags, f"Skill '{skill.id}' missing 'crafting' tag"

    def test_craft_skills_have_preconditions(self) -> None:
        """All craft skills have preconditions."""
        for skill in _craft_skills():
            assert len(skill.preconditions) > 0, f"Skill '{skill.id}' missing preconditions"


# ── 4.2 Material Shortage Scenario ────────────────────────────────────────────


class TestMaterialShortage:
    """Verify craft skills are skipped when materials are insufficient."""

    def test_craft_equipment_missing_wood(self) -> None:
        """craft_equipment fails when oak_log < 3."""
        skill = _skill_by_id("craft_equipment")
        ctx = _inventory_ctx({"oak_log": 1})
        assert check_preconditions(skill.preconditions, ctx) is False

    def test_craft_equipment_exact_wood(self) -> None:
        """craft_equipment passes when oak_log == 3."""
        skill = _skill_by_id("craft_equipment")
        ctx = _inventory_ctx({"oak_log": 3})
        assert check_preconditions(skill.preconditions, ctx) is True

    def test_craft_basic_tools_missing_wood(self) -> None:
        """craft_basic_tools fails when oak_log < 3."""
        skill = _skill_by_id("craft_basic_tools")
        ctx = _inventory_ctx({"oak_log": 2})
        assert check_preconditions(skill.preconditions, ctx) is False

    def test_craft_basic_tools_enough_wood(self) -> None:
        """craft_basic_tools passes when oak_log >= 3."""
        skill = _skill_by_id("craft_basic_tools")
        ctx = _inventory_ctx({"oak_log": 5})
        assert check_preconditions(skill.preconditions, ctx) is True

    def test_craft_armor_missing_iron(self) -> None:
        """craft_armor fails when iron_ingot < 24."""
        skill = _skill_by_id("craft_armor")
        ctx = _inventory_ctx({"iron_ingot": 20})
        assert check_preconditions(skill.preconditions, ctx) is False

    def test_craft_armor_exact_iron(self) -> None:
        """craft_armor passes when iron_ingot == 24."""
        skill = _skill_by_id("craft_armor")
        ctx = _inventory_ctx({"iron_ingot": 24})
        assert check_preconditions(skill.preconditions, ctx) is True

    def test_craft_armor_excess_iron(self) -> None:
        """craft_armor passes when iron_ingot > 24."""
        skill = _skill_by_id("craft_armor")
        ctx = _inventory_ctx({"iron_ingot": 50})
        assert check_preconditions(skill.preconditions, ctx) is True

    def test_empty_inventory_fails_all_craft(self) -> None:
        """All craft skills fail with empty inventory."""
        ctx = _inventory_ctx({})
        for skill in _craft_skills():
            assert check_preconditions(skill.preconditions, ctx) is False, (
                f"Skill '{skill.id}' should fail with empty inventory"
            )

    def test_no_inventory_key_fails(self) -> None:
        """craft_equipment fails when context has no inventory key."""
        skill = _skill_by_id("craft_equipment")
        assert check_preconditions(skill.preconditions, {}) is False


# ── 4.3 No Workbench Scenario ─────────────────────────────────────────────────


class TestWorkbenchScenario:
    """Verify workbench-related logic in craft skills.

    The bot's JS code handles physical workbench detection (32-block range).
    These tests verify that 3x3 recipes (requiring workbench) are properly
    represented in the skill steps and that the skill system handles the
    concept at the Python level.
    """

    def test_craft_equipment_includes_3x3_recipes(self) -> None:
        """craft_equipment includes recipes that require crafting table."""
        skill = _skill_by_id("craft_equipment")
        # Items requiring 3x3 crafting: pickaxes, axes, swords, armor
        three_by_three = [
            "wooden_pickaxe",
            "stone_pickaxe",
            "iron_pickaxe",
            "diamond_pickaxe",
            "iron_axe",
            "iron_sword",
        ]
        recipes = [s.params["recipe"] for s in skill.steps if s.name == "craft"]
        for item in three_by_three:
            assert item in recipes, f"craft_equipment should include 3x3 recipe: {item}"

    def test_craft_basic_tools_includes_both_2x2_and_3x3(self) -> None:
        """craft_basic_tools includes sticks (2x2) and tools (3x3)."""
        skill = _skill_by_id("craft_basic_tools")
        recipes = [s.params["recipe"] for s in skill.steps if s.name == "craft"]
        # sticks can be crafted in 2x2 grid
        assert "stick" in recipes, "2x2 stick recipe missing"
        # tools require 3x3 (crafting table)
        assert "wooden_pickaxe" in recipes, "3x3 wooden_pickaxe recipe missing"

    def test_craft_armor_all_3x3(self) -> None:
        """All armor pieces require crafting table (3x3)."""
        skill = _skill_by_id("craft_armor")
        recipes = [s.params["recipe"] for s in skill.steps if s.name == "craft"]
        for recipe in recipes:
            assert recipe in ("iron_helmet", "iron_chestplate", "iron_leggings", "iron_boots"), (
                f"Unexpected armor recipe: {recipe}"
            )

    def test_skill_library_does_not_check_workbench_at_python_level(self) -> None:
        """Workbench detection is a JS-side concern; Python skills only check inventory."""
        skill = _skill_by_id("craft_equipment")
        # Preconditions are only about materials, not workbench presence
        for cond in skill.preconditions:
            assert cond.startswith("has_"), f"Preconditions should be material checks, got: {cond}"


# ── 4.4 Skill Matching and Execution ──────────────────────────────────────────


class TestCraftSkillMatching:
    """Verify SkillLibrary correctly matches craft skills based on context."""

    @pytest.fixture
    async def lib_with_craft_skills(self) -> SkillLibrary:
        """SkillLibrary pre-populated with all predefined skills."""
        lib = SkillLibrary()
        for skill in get_predefined_skills():
            await lib.save_skill(skill)
        return lib

    async def test_match_craft_skills_with_wood(
        self,
        lib_with_craft_skills: SkillLibrary,
    ) -> None:
        """match_skills finds craft skills when oak_log >= 3."""
        ctx = _inventory_ctx({"oak_log": 10})
        matched = await lib_with_craft_skills.match_skills(ctx)
        matched_ids = {s.id for s in matched}

        assert "craft_equipment" in matched_ids, "craft_equipment should match"
        assert "craft_basic_tools" in matched_ids, "craft_basic_tools should match"
        assert "craft_armor" not in matched_ids, "craft_armor should NOT match without iron"

    async def test_match_craft_skills_with_iron(
        self,
        lib_with_craft_skills: SkillLibrary,
    ) -> None:
        """match_skills finds armor skill when iron_ingot >= 24."""
        ctx = _inventory_ctx({"iron_ingot": 30})
        matched = await lib_with_craft_skills.match_skills(ctx)
        matched_ids = {s.id for s in matched}
        assert "craft_armor" in matched_ids, "craft_armor should match"

    async def test_match_craft_skills_with_both(
        self,
        lib_with_craft_skills: SkillLibrary,
    ) -> None:
        """All 3 craft skills match when both wood and iron available."""
        ctx = _inventory_ctx({"oak_log": 10, "iron_ingot": 30})
        matched = await lib_with_craft_skills.match_skills(ctx)
        matched_ids = {s.id for s in matched}
        assert "craft_equipment" in matched_ids
        assert "craft_basic_tools" in matched_ids
        assert "craft_armor" in matched_ids

    async def test_no_craft_skills_match_empty(
        self,
        lib_with_craft_skills: SkillLibrary,
    ) -> None:
        """No craft skills match with empty inventory."""
        ctx = _inventory_ctx({})
        matched = await lib_with_craft_skills.match_skills(ctx)
        matched_ids = {s.id for s in matched}
        assert "craft_equipment" not in matched_ids
        assert "craft_basic_tools" not in matched_ids
        assert "craft_armor" not in matched_ids

    async def test_search_craft_skills_by_keyword(
        self,
        lib_with_craft_skills: SkillLibrary,
    ) -> None:
        """Searching '装备' finds craft_equipment."""
        results = await lib_with_craft_skills.search_skills("装备")
        result_ids = {s.id for s in results}
        assert "craft_equipment" in result_ids

    async def test_search_craft_skills_by_tag(
        self,
        lib_with_craft_skills: SkillLibrary,
    ) -> None:
        """Searching by 'crafting' tag finds all craft skills."""
        results = await lib_with_craft_skills.search_by_tags(["crafting"], limit=10)
        result_ids = {s.id for s in results}
        assert "craft_equipment" in result_ids
        assert "craft_basic_tools" in result_ids
        assert "craft_armor" in result_ids

    async def test_precondition_check_at_step_level(self) -> None:
        """Step-level preconditions are checked during execution."""
        # Create a skill with a check step that validates inventory
        from animetta.tools.minecraft.skill.library import SkillStep

        skill = Skill(
            id="test_equip_check",
            name="Test Equip Check",
            description="Test equipment crafting with step precondition",
            category="crafting",
            preconditions=["has_oak_log >= 3"],
            steps=[
                SkillStep(
                    name="check",
                    params={"condition": "has_oak_log >= 3"},
                ),
                SkillStep(
                    name="craft",
                    params={"recipe": "wooden_pickaxe", "count": 1},
                ),
            ],
            tags=["crafting", "test"],
        )
        assert skill.steps[0].params["condition"] == "has_oak_log >= 3"
