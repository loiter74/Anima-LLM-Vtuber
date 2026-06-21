"""
Integration tests for MinecraftPlanner + SkillLibrary.

Verifies that the planner correctly uses the SkillLibrary for
skill-based plan generation before falling back to LLM.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.tools.minecraft.planner import (
    MinecraftPlanner,
    ModeSelector,
    Plan,
    PlannerError,
)
from animetta.tools.minecraft.skill_library import Skill, SkillLibrary, SkillStep

# ── Fixtures ──


def _make_skill(
    skill_id: str = "build_house",
    name: str = "建房子",
    description: str = "使用圆石和木板建造简易房屋",
    tags: list[str] | None = None,
) -> Skill:
    """Create a test skill with realistic steps."""
    return Skill(
        id=skill_id,
        name=name,
        description=description,
        category="building",
        preconditions=["has_cobblestone >= 32"],
        steps=[
            SkillStep(name="check", params={"condition": "has_cobblestone >= 32"}),
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="place", params={"block_type": "cobblestone", "x": 0, "y": 64, "z": 0}),
        ],
        tags=tags or ["building", "house"],
    )


def _mock_llm(response_json: str | None = None) -> MagicMock:
    """Create a mock LLM service."""
    llm = MagicMock()
    if response_json is None:
        response_json = '{"goal": "test", "steps": [{"action": "goto", "params": {"x": 0, "y": 64, "z": 0}}]}'
    mock_response = MagicMock()
    mock_response.content = response_json
    llm.chat = AsyncMock(return_value=mock_response)
    return llm


# ── Tests ──


class TestPlannerWithSkillLibrary:
    """MinecraftPlanner stores and exposes the SkillLibrary."""

    def test_planner_with_skill_library(self) -> None:
        """SkillLibrary injected via constructor is stored."""
        lib = SkillLibrary()
        planner = MinecraftPlanner(llm_service=_mock_llm(), skill_library=lib)

        assert planner._skill_library is lib

    def test_planner_without_skill_library(self) -> None:
        """None skill_library is fine — planner still works."""
        planner = MinecraftPlanner(llm_service=_mock_llm())

        assert planner._skill_library is None


class TestPlanFindsMatchingSkill:
    """plan() returns a Plan from SkillLibrary when a skill matches."""

    async def test_plan_finds_matching_skill(self) -> None:
        """When search_skills returns a skill, plan() returns a Plan without calling LLM."""
        lib = SkillLibrary()
        skill = _make_skill()
        await lib.save_skill(skill)

        llm = _mock_llm()
        planner = MinecraftPlanner(llm_service=llm, skill_library=lib)

        plan = await planner.plan("建房子")

        # Plan should be built from skill steps
        assert isinstance(plan, Plan)
        assert len(plan.steps) == len(skill.steps)
        assert plan.goal == "建房子"

        # LLM should NOT have been called
        llm.chat.assert_not_awaited()

    async def test_plan_uses_skill_step_params(self) -> None:
        """Plan steps carry the skill's step params."""
        lib = SkillLibrary()
        skill = _make_skill()
        await lib.save_skill(skill)

        planner = MinecraftPlanner(llm_service=_mock_llm(), skill_library=lib)
        plan = await planner.plan("建房子")

        # First step should be check with condition
        assert plan.steps[0].action == "check"
        assert plan.steps[0].params == {"condition": "has_cobblestone >= 32"}

    async def test_plan_stores_last_plan(self) -> None:
        """Plan is stored as last_plan after generation."""
        lib = SkillLibrary()
        skill = _make_skill()
        await lib.save_skill(skill)

        planner = MinecraftPlanner(llm_service=_mock_llm(), skill_library=lib)
        plan = await planner.plan("建房子")

        assert planner.last_plan is plan


class TestPlanFallsBackToLLM:
    """plan() calls LLM when SkillLibrary has no matching skill."""

    async def test_plan_falls_back_to_llm(self) -> None:
        """When search_skills returns empty, plan() calls LLM."""
        lib = SkillLibrary()
        # No skills saved → search returns []

        llm = _mock_llm()
        planner = MinecraftPlanner(llm_service=llm, skill_library=lib)

        plan = await planner.plan("do something unrelated")

        # LLM should have been called
        llm.chat.assert_awaited_once()

        # Plan should come from LLM response
        assert isinstance(plan, Plan)
        assert len(plan.steps) > 0

    async def test_plan_falls_back_when_no_library(self) -> None:
        """Without SkillLibrary, plan() always calls LLM."""
        llm = _mock_llm()
        planner = MinecraftPlanner(llm_service=llm)  # no skill_library

        plan = await planner.plan("build a house")

        llm.chat.assert_awaited_once()
        assert isinstance(plan, Plan)

    async def test_plan_raises_without_llm(self) -> None:
        """plan() raises PlannerError when no LLM and no matching skill."""
        lib = SkillLibrary()
        planner = MinecraftPlanner(skill_library=lib)  # no llm, no matching skill

        with pytest.raises(PlannerError, match="No LLM service configured"):
            await planner.plan("anything")


class TestModeSelectorPassesSkillLibrary:
    """ModeSelector correctly wires SkillLibrary into the planner."""

    def test_mode_selector_passes_skill_library(self) -> None:
        """ModeSelector injects SkillLibrary into planner when planner doesn't have one."""
        lib = SkillLibrary()
        planner = MinecraftPlanner(llm_service=_mock_llm())  # no library
        ModeSelector(planner, skill_library=lib)

        assert planner._skill_library is lib

    def test_mode_selector_does_not_override_existing(self) -> None:
        """ModeSelector doesn't override planner's existing SkillLibrary."""
        lib1 = SkillLibrary()
        lib2 = SkillLibrary()
        planner = MinecraftPlanner(llm_service=_mock_llm(), skill_library=lib1)
        ModeSelector(planner, skill_library=lib2)

        # Should keep the original
        assert planner._skill_library is lib1

    def test_mode_selector_without_skill_library(self) -> None:
        """ModeSelector works fine without SkillLibrary."""
        planner = MinecraftPlanner(llm_service=_mock_llm())
        ModeSelector(planner)  # no skill_library

        assert planner._skill_library is None

    async def test_mode_selector_uses_skill_library(self) -> None:
        """select_mode generates plan via SkillLibrary when goal matches a skill."""
        lib = SkillLibrary()
        skill = _make_skill()
        await lib.save_skill(skill)

        llm = _mock_llm()
        planner = MinecraftPlanner(llm_service=llm, skill_library=lib)
        selector = ModeSelector(planner)

        selector.set_goal("建房子")
        result = await selector.select_mode()

        assert result["mode"] == "planner"
        assert result["plan"] is not None
        assert len(result["plan"]) == len(skill.steps)
        # LLM should not be called
        llm.chat.assert_not_awaited()

    async def test_mode_selector_rule_mode_without_goal(self) -> None:
        """select_mode returns rule mode when no goal is set."""
        planner = MinecraftPlanner(llm_service=_mock_llm())
        selector = ModeSelector(planner)

        result = await selector.select_mode()

        assert result["mode"] == "rule"
        assert result["plan"] is None
