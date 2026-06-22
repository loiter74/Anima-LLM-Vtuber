"""Unit tests for skill execution engine and precondition checking."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from animetta.tools.minecraft.skill.library import (
    Skill,
    SkillStep,
    check_preconditions,
    execute_skill,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_skill(
    steps: list[SkillStep] | None = None,
    preconditions: list[str] | None = None,
    **kwargs: Any,
) -> Skill:
    return Skill(
        id="test-skill",
        name="test",
        description="test skill",
        steps=steps or [],
        preconditions=preconditions or [],
        **kwargs,
    )


def _success_bridge(*responses: dict[str, Any]) -> AsyncMock:
    """Create a mock bridge that returns success responses in order."""
    bridge = AsyncMock()
    bridge.send_command = AsyncMock(
        side_effect=[
            {"status": "success", "result": r} if isinstance(r, dict) else {"status": "success", "result": r}
            for r in responses
        ]
    )
    return bridge


def _bridge_with_sequence(responses: list) -> AsyncMock:
    """Create a mock bridge with a sequence of responses (can include exceptions)."""
    bridge = AsyncMock()

    async def _side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        resp = responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    bridge.send_command = AsyncMock(side_effect=_side_effect)
    return bridge


# ── Precondition Tests ───────────────────────────────────────────────────────


class TestCheckPreconditionsNumeric:
    """Numeric comparison preconditions."""

    def test_check_preconditions_numeric_gt(self) -> None:
        assert check_preconditions(["health > 6"], {"health": 10}) is True
        assert check_preconditions(["health > 6"], {"health": 3}) is False

    def test_numeric_lt(self) -> None:
        assert check_preconditions(["food < 15"], {"food": 10}) is True
        assert check_preconditions(["food < 15"], {"food": 20}) is False

    def test_numeric_gte(self) -> None:
        assert check_preconditions(["level >= 5"], {"level": 5}) is True
        assert check_preconditions(["level >= 5"], {"level": 4}) is False

    def test_numeric_lte(self) -> None:
        assert check_preconditions(["danger <= 2"], {"danger": 2}) is True
        assert check_preconditions(["danger <= 2"], {"danger": 3}) is False

    def test_numeric_eq(self) -> None:
        assert check_preconditions(["phase == 3"], {"phase": 3}) is True
        assert check_preconditions(["phase == 3"], {"phase": 4}) is False

    def test_numeric_neq(self) -> None:
        assert check_preconditions(["phase != 0"], {"phase": 1}) is True
        assert check_preconditions(["phase != 0"], {"phase": 0}) is False

    def test_numeric_missing_key(self) -> None:
        assert check_preconditions(["health > 6"], {}) is False

    def test_numeric_none_context(self) -> None:
        assert check_preconditions(["health > 6"], None) is False


class TestCheckPreconditionsBoolean:
    """Boolean flag preconditions."""

    def test_check_preconditions_boolean_true(self) -> None:
        assert check_preconditions(["is_day"], {"is_day": True}) is True

    def test_boolean_false(self) -> None:
        assert check_preconditions(["is_day"], {"is_day": False}) is False

    def test_boolean_missing(self) -> None:
        assert check_preconditions(["is_day"], {}) is False

    def test_boolean_truthy_value(self) -> None:
        assert check_preconditions(["is_day"], {"is_day": 1}) is True

    def test_boolean_falsy_value(self) -> None:
        assert check_preconditions(["is_day"], {"is_day": 0}) is False


class TestCheckPreconditionsInventory:
    """Inventory ``has_X`` preconditions."""

    def test_check_preconditions_inventory_present(self) -> None:
        ctx = {"inventory": {"pickaxe": 1, "wood": 10}}
        assert check_preconditions(["has_pickaxe"], ctx) is True

    def test_inventory_absent(self) -> None:
        ctx = {"inventory": {"wood": 10}}
        assert check_preconditions(["has_pickaxe"], ctx) is False

    def test_inventory_zero_count(self) -> None:
        ctx = {"inventory": {"pickaxe": 0}}
        assert check_preconditions(["has_pickaxe"], ctx) is False

    def test_inventory_no_inventory_key(self) -> None:
        assert check_preconditions(["has_pickaxe"], {}) is False

    def test_inventory_multiple(self) -> None:
        ctx = {"inventory": {"pickaxe": 1, "torch": 5}}
        assert check_preconditions(["has_pickaxe", "has_torch"], ctx) is True
        assert check_preconditions(["has_pickaxe", "has_sword"], ctx) is False


class TestCheckPreconditionsEdgeCases:
    """Edge cases for precondition checking."""

    def test_empty_conditions(self) -> None:
        assert check_preconditions([], {"health": 1}) is True

    def test_string_comparison_eq(self) -> None:
        assert check_preconditions(['biome == "forest"'], {"biome": "forest"}) is True

    def test_string_comparison_neq(self) -> None:
        assert check_preconditions(['biome != "desert"'], {"biome": "forest"}) is True

    def test_multiple_conditions_all_pass(self) -> None:
        ctx = {"health": 10, "is_day": True, "inventory": {"pickaxe": 1}}
        conds = ["health > 6", "is_day", "has_pickaxe"]
        assert check_preconditions(conds, ctx) is True

    def test_multiple_conditions_one_fails(self) -> None:
        ctx = {"health": 3, "is_day": True, "inventory": {"pickaxe": 1}}
        conds = ["health > 6", "is_day", "has_pickaxe"]
        assert check_preconditions(conds, ctx) is False


# ── Execution Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestExecuteSkill:
    """execute_skill() behavior."""

    async def test_execute_skill_success(self) -> None:
        steps = [
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="collect", params={"block_type": "log", "count": 3}),
        ]
        skill = _make_skill(steps=steps)
        bridge = _success_bridge({}, {"collected": 3})

        result = await execute_skill(skill, bridge)

        assert result.success is True
        assert result.skill_id == "test-skill"
        assert result.failed_at is None
        assert bridge.send_command.call_count == 2

    async def test_execute_skill_step_failure(self) -> None:
        steps = [
            SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
            SkillStep(name="mine", params={"block_type": "diamond_ore"}),
        ]
        skill = _make_skill(steps=steps)
        bridge = _bridge_with_sequence([
            {"status": "success", "result": {}},
            {"status": "error", "result": "No diamond ore found"},
        ])

        result = await execute_skill(skill, bridge)

        assert result.success is False
        assert result.failed_at == 1
        assert "diamond_ore" in (result.reason or "") or "error" in (result.reason or "").lower()

    async def test_execute_skill_timeout_retry(self) -> None:
        """First attempt times out, retry succeeds."""
        steps = [
            SkillStep(
                name="goto",
                params={"x": 100, "y": 64, "z": 200},
                retry=1,
                timeout=5.0,
            ),
        ]
        skill = _make_skill(steps=steps)
        bridge = _bridge_with_sequence([
            TimeoutError("timed out"),
            {"status": "success", "result": {}},
        ])

        result = await execute_skill(skill, bridge)

        assert result.success is True
        assert bridge.send_command.call_count == 2

    async def test_execute_skill_retry_exhausted(self) -> None:
        """All retries fail."""
        steps = [
            SkillStep(
                name="goto",
                params={"x": 100, "y": 64, "z": 200},
                retry=1,
                timeout=5.0,
            ),
        ]
        skill = _make_skill(steps=steps)
        bridge = _bridge_with_sequence([
            TimeoutError("timed out"),
            TimeoutError("timed out again"),
        ])

        result = await execute_skill(skill, bridge)

        assert result.success is False
        assert result.failed_at == 0
        assert "timed out" in (result.reason or "").lower()

    async def test_execute_skill_context_merge(self) -> None:
        """Results from steps are merged into context for downstream steps."""
        steps = [
            SkillStep(name="check", params={"condition": "scan"}),
            SkillStep(name="collect", params={"block_type": "log"}),
        ]
        skill = _make_skill(steps=steps)
        bridge = _bridge_with_sequence([
            {"status": "success", "result": {"nearest_tree": (10, 64, 20)}},
            {"status": "success", "result": {"collected": 1}},
        ])

        result = await execute_skill(skill, bridge, context={"health": 10})

        assert result.success is True
        assert "nearest_tree" in result.context_updates

    async def test_execute_skill_preconditions_fail(self) -> None:
        skill = _make_skill(
            steps=[SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0})],
            preconditions=["is_day"],
        )
        bridge = _success_bridge({})

        result = await execute_skill(skill, bridge, context={"is_day": False})

        assert result.success is False
        assert result.failed_at == -1
        assert "precondition" in (result.reason or "").lower()
        bridge.send_command.assert_not_called()

    async def test_execute_skill_step_preconditions_fail(self) -> None:
        steps = [
            SkillStep(
                name="mine",
                params={"block_type": "stone"},
                preconditions=["has_pickaxe"],
            ),
        ]
        skill = _make_skill(steps=steps)
        bridge = _success_bridge({})

        result = await execute_skill(skill, bridge, context={"inventory": {}})

        assert result.success is False
        assert result.failed_at == 0
        assert "precondition" in (result.reason or "").lower()


@pytest.mark.asyncio
class TestSkillStatsUpdate:
    """Stats tracking after execution."""

    async def test_skill_stats_update_success(self) -> None:
        skill = _make_skill(
            steps=[SkillStep(name="chat", params={"message": "hi"})],
        )
        bridge = _success_bridge({})

        await execute_skill(skill, bridge)

        assert skill.success_count == 1
        assert skill.fail_count == 0
        assert skill.last_used != ""
        assert skill.avg_duration >= 0

    async def test_skill_stats_update_failure(self) -> None:
        skill = _make_skill(
            steps=[SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0})],
        )
        bridge = _bridge_with_sequence([{"status": "error", "result": "blocked"}])

        await execute_skill(skill, bridge)

        assert skill.success_count == 0
        assert skill.fail_count == 1

    async def test_skill_stats_ema_duration(self) -> None:
        """avg_duration uses exponential moving average."""
        skill = _make_skill(
            steps=[SkillStep(name="chat", params={"message": "hi"})],
        )

        # First execution — fresh bridge
        bridge1 = _success_bridge({})
        await execute_skill(skill, bridge1)
        first_duration = skill.avg_duration
        assert first_duration > 0

        # Second execution — fresh bridge so side_effect isn't exhausted
        bridge2 = _success_bridge({})
        await execute_skill(skill, bridge2)
        assert skill.avg_duration > 0
        assert skill.success_count == 2
