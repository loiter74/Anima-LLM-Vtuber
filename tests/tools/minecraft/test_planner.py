from __future__ import annotations

from animetta.tools.minecraft.planner import (
    MinecraftPlanner,
    ModeSelector,
    Plan,
    PlannerError,
    PlanStep,
)

"""Tests for MinecraftPlanner — task decomposition and plan step generation."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Fixtures ──

@pytest.fixture
def mock_llm():
    """Create a mock LLM service with a chat method."""
    llm = MagicMock()
    llm.chat = AsyncMock()
    return llm


def sample_plan_json():
    """Valid plan JSON the LLM might return."""
    return {
        "goal": "Build a small house",
        "reasoning": "Need oak logs for walls and planks for floor",
        "steps": [
            {"action": "collect", "params": {"block_type": "oak_log", "count": 16},
             "description": "Collect 16 oak logs"},
            {"action": "place", "params": {"block_type": "oak_planks", "x": 0, "y": 65, "z": 0},
             "description": "Place floor"},
        ]
    }


# ── Test Classes ──

class TestPlanStepDataclass:
    """PlanStep data model tests."""

    def test_default_values(self):
        step = PlanStep(action="goto")
        assert step.action == "goto"
        assert step.params == {}
        assert step.description == ""

    def test_full_creation(self):
        step = PlanStep(
            action="collect",
            params={"block_type": "oak_log", "count": 16},
            description="Collect 16 oak logs",
        )
        assert step.action == "collect"
        assert step.params == {"block_type": "oak_log", "count": 16}
        assert step.description == "Collect 16 oak logs"


class TestPlanDataclass:
    """Plan data model tests."""

    def test_default_values(self):
        plan = Plan(goal="test")
        assert plan.goal == "test"
        assert plan.steps == []
        assert plan.status == "pending"

    def test_with_steps(self):
        steps = [
            PlanStep(action="goto", params={"x": 0, "y": 64, "z": 0}),
            PlanStep(action="mine", params={"block_type": "stone"}),
        ]
        plan = Plan(goal="mine stone", steps=steps, status="running")
        assert len(plan.steps) == 2
        assert plan.status == "running"
        assert plan.steps[0].action == "goto"


class TestMinecraftPlannerInit:
    """Planner initialization tests."""

    def test_init_without_llm(self):
        planner = MinecraftPlanner()
        assert planner._llm is None
        assert planner._last_plan is None

    def test_init_with_llm(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)
        assert planner._llm is mock_llm

    def test_set_llm_updates_service(self, mock_llm):
        planner = MinecraftPlanner()
        planner.set_llm(mock_llm)
        assert planner._llm is mock_llm


class TestMinecraftPlannerPlan:
    """Planner.plan() tests."""

    async def test_plan_no_llm_raises_error(self):
        planner = MinecraftPlanner()
        with pytest.raises(PlannerError, match="No LLM service"):
            await planner.plan("build a house")

    async def test_plan_success(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)

        plan_data = sample_plan_json()
        response = MagicMock()
        response.content = json.dumps(plan_data)
        mock_llm.chat.return_value = response

        result = await planner.plan("Build a small house")

        assert result.goal == "Build a small house"
        assert len(result.steps) == 2
        assert result.steps[0].action == "collect"
        assert result.steps[0].params == {"block_type": "oak_log", "count": 16}
        assert result.steps[1].action == "place"
        assert planner.last_plan is result

    async def test_plan_with_context(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)

        plan_data = sample_plan_json()
        response = MagicMock()
        response.content = json.dumps(plan_data)
        mock_llm.chat.return_value = response

        context = {
            "position": {"x": 100, "y": 64, "z": 200},
            "inventory": {"oak_log": 5},
            "time": "day",
        }
        result = await planner.plan("build something", context)

        assert result.goal == "build something"
        # Verify context was included in the user prompt
        call_args = mock_llm.chat.call_args[1]
        messages = call_args["messages"]
        user_msg = messages[1]["content"]
        assert "current position" in user_msg
        assert "100" in user_msg

    async def test_plan_with_inventory_empty_context(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)

        plan_data = sample_plan_json()
        response = MagicMock()
        response.content = json.dumps(plan_data)
        mock_llm.chat.return_value = response

        context = {"inventory": {}}
        await planner.plan("gather wood", context)

        call_args = mock_llm.chat.call_args[1]
        user_msg = call_args["messages"][1]["content"]
        assert "empty" in user_msg

    async def test_plan_invalid_json_raises_error(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)

        response = MagicMock()
        response.content = "not valid json at all"
        mock_llm.chat.return_value = response

        with pytest.raises(PlannerError, match="Failed to parse"):
            await planner.plan("do something")

    async def test_plan_llm_chat_exception(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)

        mock_llm.chat.side_effect = RuntimeError("LLM connection failed")

        with pytest.raises(PlannerError, match="Planning failed"):
            await planner.plan("do something")


class TestMinecraftPlannerExtractJson:
    """Planner._extract_json() tests."""

    def test_extract_direct_json(self):
        planner = MinecraftPlanner()
        result = planner._extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_extract_from_markdown_code_block(self):
        planner = MinecraftPlanner()
        text = '```json\n{"key": "value"}\n```'
        result = planner._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_from_generic_code_block(self):
        planner = MinecraftPlanner()
        text = '```\n{"key": "value"}\n```'
        result = planner._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_no_valid_json_raises(self):
        import json as json_mod
        planner = MinecraftPlanner()
        with pytest.raises(json_mod.JSONDecodeError):
            planner._extract_json("just plain text with no json")


class TestMinecraftPlannerParsePlan:
    """Planner._parse_plan() tests."""

    def test_parse_plan_with_steps(self):
        planner = MinecraftPlanner()
        raw = sample_plan_json()
        plan = planner._parse_plan("Build house", raw)
        assert plan.goal == "Build house"
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "collect"

    def test_parse_plan_empty_steps(self):
        planner = MinecraftPlanner()
        raw = {"goal": "idle", "steps": []}
        plan = planner._parse_plan("idle", raw)
        assert plan.goal == "idle"
        assert len(plan.steps) == 0

    def test_parse_plan_missing_description(self):
        planner = MinecraftPlanner()
        raw = {
            "goal": "test",
            "steps": [{"action": "goto", "params": {"x": 1, "y": 2, "z": 3}}]
        }
        plan = planner._parse_plan("test", raw)
        assert plan.steps[0].description == ""
        assert plan.steps[0].params == {"x": 1, "y": 2, "z": 3}


class TestMinecraftPlannerValidatePlan:
    """Planner._validate_plan() tests."""

    def test_validate_known_actions_pass(self):
        planner = MinecraftPlanner()
        plan = Plan(
            goal="test",
            steps=[
                PlanStep(action="goto", params={"x": 0, "y": 64, "z": 0}),
                PlanStep(action="collect", params={"block_type": "wood", "count": 5}),
                PlanStep(action="mine", params={"block_type": "stone", "count": 10}),
            ]
        )
        planner._validate_plan(plan)  # Should not raise

    def test_validate_unknown_action_logs_warning(self):
        planner = MinecraftPlanner()
        plan = Plan(
            goal="test",
            steps=[PlanStep(action="fly_to_moon", params={})]
        )
        planner._validate_plan(plan)  # Should not raise, just log warning

    def test_validate_non_dict_params_fixed(self):
        planner = MinecraftPlanner()
        step = PlanStep(action="goto")
        step.params = "not a dict"  # type: ignore[assignment]
        plan = Plan(goal="test", steps=[step])
        planner._validate_plan(plan)
        assert step.params == {}


class TestMinecraftPlannerReplan:
    """Planner.replan() tests."""

    async def test_replan_no_previous_plan_raises_error(self):
        planner = MinecraftPlanner()
        with pytest.raises(PlannerError, match="No previous plan"):
            await planner.replan(0, "step failed")

    async def test_replan_success(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)

        # Set a previous plan
        planner._last_plan = Plan(
            goal="Build a house",
            steps=[
                PlanStep(action="collect", params={"block_type": "oak_log", "count": 16}),
                PlanStep(action="place", params={"block_type": "oak_planks", "x": 0, "y": 65, "z": 0}),
            ],
        )

        plan_data = sample_plan_json()
        response = MagicMock()
        response.content = json.dumps(plan_data)
        mock_llm.chat.return_value = response

        result = await planner.replan(0, "No oak trees nearby")

        assert result is not None
        # Verify context includes completed_steps
        call_args = mock_llm.chat.call_args[1]
        user_msg = call_args["messages"][1]["content"]
        assert "step 1" in user_msg or "step 0" in user_msg
        assert "failed" in user_msg


class TestModeSelector:
    """ModeSelector tests."""

    def test_init_stores_planner(self):
        planner = MinecraftPlanner()
        selector = ModeSelector(planner)
        assert selector._planner is planner
        assert selector._has_goal is False
        assert selector._goal is None

    def test_set_goal_with_valid_string(self):
        planner = MinecraftPlanner()
        selector = ModeSelector(planner)
        selector.set_goal("build a castle")
        assert selector._goal == "build a castle"
        assert selector._has_goal is True

    def test_set_goal_with_empty_string(self):
        planner = MinecraftPlanner()
        selector = ModeSelector(planner)
        selector.set_goal("")
        assert selector._has_goal is False

    def test_set_goal_with_none(self):
        planner = MinecraftPlanner()
        selector = ModeSelector(planner)
        selector.set_goal(None)
        assert selector._has_goal is False

    async def test_select_mode_no_goal_returns_rule(self):
        planner = MinecraftPlanner()
        selector = ModeSelector(planner)
        result = await selector.select_mode()
        assert result["mode"] == "rule"
        assert result["plan"] is None

    async def test_select_mode_with_goal_returns_planner(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)

        plan_data = sample_plan_json()
        response = MagicMock()
        response.content = json.dumps(plan_data)
        mock_llm.chat.return_value = response

        selector = ModeSelector(planner)
        selector.set_goal("build a house")
        result = await selector.select_mode()

        assert result["mode"] == "planner"
        assert len(result["plan"]) == 2
        assert result["plan"][0]["action"] == "collect"

    async def test_select_mode_planner_error_falls_back(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)
        mock_llm.chat.side_effect = PlannerError("test failure")

        selector = ModeSelector(planner)
        selector.set_goal("build a house")
        result = await selector.select_mode()

        assert result["mode"] == "rule"
        assert result["plan"] is None
        assert "test failure" in result["error"]

    async def test_select_mode_passes_context_to_planner(self, mock_llm):
        planner = MinecraftPlanner(llm_service=mock_llm)

        plan_data = sample_plan_json()
        response = MagicMock()
        response.content = json.dumps(plan_data)
        mock_llm.chat.return_value = response

        selector = ModeSelector(planner)
        selector.set_goal("build house")
        context = {"position": {"x": 42, "y": 64, "z": 42}}
        result = await selector.select_mode(context)

        assert result["mode"] == "planner"
        call_args = mock_llm.chat.call_args[1]
        user_msg = call_args["messages"][1]["content"]
        assert "42" in user_msg
