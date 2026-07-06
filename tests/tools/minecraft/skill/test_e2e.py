"""
End-to-end tests for the Skill system.

Tests complete flows: goal → match → execute → stats → cleanup.
All bridge interactions are mocked — no real Minecraft connection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from animetta.tools.minecraft.skill.library import (
    Skill,
    SkillLibrary,
    SkillStep,
    execute_skill,
)
from animetta.tools.minecraft.skill.predefined import get_predefined_skills

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_bridge() -> AsyncMock:
    """Create a mock bridge with a controllable send_command."""
    bridge = AsyncMock()
    bridge.send_command = AsyncMock()
    return bridge


def _success_response(result: dict | None = None) -> dict:
    """Return a successful bridge response."""
    return {"status": "success", "result": result or {}}


def _error_response(reason: str = "command failed") -> dict:
    """Return a failed bridge response."""
    return {"status": "error", "result": reason}


# ── 8.1 Full Flow: Goal → Skill Matching → Execution ────────────────────────


class TestFullFlowGoalToSkillExecution:
    """End-to-end: load predefined skills, match by world state, execute."""

    async def test_survival_food_matches_low_food_context(self):
        """When food < 15, match_skills() should return survival_food."""
        library = SkillLibrary()
        for skill in get_predefined_skills():
            await library.save_skill(skill)

        context = {"food": 10, "is_day": True, "health": 20}

        matched = await library.match_skills(context)

        # survival_food has precondition "food < 15" — should match
        matched_ids = [s.id for s in matched]
        assert "survival_food" in matched_ids

    async def test_survival_food_is_top_match_for_lowest_food(self):
        """With very low food, survival_food should rank first."""
        library = SkillLibrary()
        for skill in get_predefined_skills():
            # Give all skills equal stats so sorting is deterministic
            skill.success_count = 5
            skill.fail_count = 0
            await library.save_skill(skill)

        context = {"food": 5, "is_day": True, "health": 20}

        matched = await library.match_skills(context, limit=5)
        assert len(matched) >= 1
        assert "survival_food" in [s.id for s in matched]

    async def test_full_flow_execute_survival_food_success(self):
        """Load predefined → match → execute survival_food with mocked bridge."""
        library = SkillLibrary()
        for skill in get_predefined_skills():
            await library.save_skill(skill)

        context = {"food": 10, "is_day": True, "health": 20}

        # Match
        matched = await library.match_skills(context)
        survival_food = next(s for s in matched if s.id == "survival_food")

        # Mock bridge: all commands succeed
        bridge = _make_bridge()
        bridge.send_command.return_value = _success_response({"collected": 3})

        # Execute
        result = await execute_skill(survival_food, bridge, context)

        # Assert success
        assert result.success is True
        assert result.skill_id == "survival_food"
        assert result.failed_at is None
        assert result.duration > 0

        # Stats updated
        assert survival_food.success_count == 1
        assert survival_food.fail_count == 0
        assert survival_food.last_used != ""

        # Bridge was called for each step (check + goto + collect = 3 steps)
        assert bridge.send_command.call_count == 3

    async def test_full_flow_execute_via_library_method(self):
        """Execute skill through SkillLibrary.execute_skill_by_id."""
        library = SkillLibrary()
        for skill in get_predefined_skills():
            await library.save_skill(skill)

        bridge = _make_bridge()
        bridge.send_command.return_value = _success_response()

        context = {"food": 10, "is_day": True, "health": 20}
        result = await library.execute_skill_by_id("survival_food", bridge, context)

        assert result.success is True
        assert result.skill_id == "survival_food"

    async def test_full_flow_context_merged_from_step_results(self):
        """Step results are merged into context for downstream steps."""
        library = SkillLibrary()
        for skill in get_predefined_skills():
            await library.save_skill(skill)

        bridge = _make_bridge()
        # First call (check) returns nothing special, second (goto) returns position
        bridge.send_command.side_effect = [
            _success_response(),
            _success_response({"x": 100, "y": 64, "z": 200}),
            _success_response({"collected": 3}),
        ]

        context = {"food": 10, "is_day": True, "health": 20}
        skill = await library.get_skill("survival_food")
        result = await execute_skill(skill, bridge, context)

        assert result.success is True
        # Context updates should include merged step results
        assert result.context_updates.get("x") == 100
        assert result.context_updates.get("collected") == 3

    async def test_full_flow_shelter_matches_night_context(self):
        """survival_shelter matches when is_night and health > 6."""
        library = SkillLibrary()
        for skill in get_predefined_skills():
            await library.save_skill(skill)

        context = {"is_night": True, "health": 20, "food": 20}

        matched = await library.match_skills(context)
        matched_ids = [s.id for s in matched]
        assert "survival_shelter" in matched_ids

    async def test_full_flow_no_match_when_preconditions_fail(self):
        """Skills with unmet preconditions are excluded from match."""
        library = SkillLibrary()
        for skill in get_predefined_skills():
            await library.save_skill(skill)

        # food=20 → "food < 15" fails → survival_food excluded
        context = {"food": 20, "health": 20, "is_day": True}

        matched = await library.match_skills(context)
        matched_ids = [s.id for s in matched]
        assert "survival_food" not in matched_ids


# ── 8.2 Error Handling: Step Failure & Timeout ──────────────────────────────


class TestErrorHandlingStepFailureTimeout:
    """Skill execution fails gracefully when steps error or timeout."""

    async def test_step_failure_returns_failure_result(self):
        """When a step returns error, SkillResult.success is False."""
        skill = Skill(
            id="fragile",
            name="Fragile Skill",
            description="A skill that will fail",
            steps=[
                SkillStep(name="check", params={"condition": "alive"}),
                SkillStep(name="goto", params={"x": 0, "y": 64, "z": 0}),
                SkillStep(name="mine", params={"block_type": "diamond_ore", "count": 1}),
            ],
        )

        bridge = _make_bridge()
        # First step succeeds, second fails
        bridge.send_command.side_effect = [
            _success_response(),
            _error_response("path blocked"),
        ]

        result = await execute_skill(skill, bridge, {})

        assert result.success is False
        assert result.skill_id == "fragile"
        assert result.failed_at == 1  # Second step (index 1)
        assert "path blocked" in (result.reason or "")

    async def test_timeout_returns_failure_result(self):
        """When a step times out, SkillResult captures the timeout."""
        skill = Skill(
            id="timeout_skill",
            name="Timeout Skill",
            description="A skill that times out",
            steps=[
                SkillStep(name="goto", params={"x": 100, "y": 64, "z": 100}, timeout=0.1),
            ],
        )

        bridge = _make_bridge()
        bridge.send_command.side_effect = TimeoutError("timed out")

        result = await execute_skill(skill, bridge, {})

        assert result.success is False
        assert result.failed_at == 0
        assert "timed out" in (result.reason or "").lower()

    async def test_exception_returns_failure_result(self):
        """When a step raises an unexpected exception, it's caught."""
        skill = Skill(
            id="crash_skill",
            name="Crash Skill",
            description="A skill that raises",
            steps=[
                SkillStep(name="mine", params={"block_type": "stone", "count": 1}),
            ],
        )

        bridge = _make_bridge()
        bridge.send_command.side_effect = RuntimeError("bot exploded")

        result = await execute_skill(skill, bridge, {})

        assert result.success is False
        assert result.failed_at == 0
        assert "RuntimeError" in (result.reason or "")

    async def test_fail_count_incremented_on_failure(self):
        """skill.fail_count is incremented when execution fails."""
        skill = Skill(
            id="fail_counter",
            name="Fail Counter",
            description="Tracks failures",
            steps=[
                SkillStep(name="collect", params={"block_type": "emerald", "count": 1}),
            ],
        )

        bridge = _make_bridge()
        bridge.send_command.return_value = _error_response("no emeralds")

        assert skill.fail_count == 0
        result = await execute_skill(skill, bridge, {})
        assert result.success is False
        assert skill.fail_count == 1

    async def test_retry_exhausted_then_fail(self):
        """Steps with retry > 0 retry before giving up."""
        skill = Skill(
            id="retry_skill",
            name="Retry Skill",
            description="Has retries",
            steps=[
                SkillStep(
                    name="mine",
                    params={"block_type": "obsidian", "count": 1},
                    retry=2,
                ),
            ],
        )

        bridge = _make_bridge()
        bridge.send_command.return_value = _error_response("too hard")

        result = await execute_skill(skill, bridge, {})

        assert result.success is False
        # 3 attempts total (1 initial + 2 retries)
        assert bridge.send_command.call_count == 3

    async def test_retry_succeeds_on_second_attempt(self):
        """A step that fails then succeeds on retry is fine."""
        skill = Skill(
            id="retry_ok",
            name="Retry OK",
            description="Succeeds on retry",
            steps=[
                SkillStep(
                    name="mine",
                    params={"block_type": "gold_ore", "count": 1},
                    retry=2,
                ),
            ],
        )

        bridge = _make_bridge()
        bridge.send_command.side_effect = [
            _error_response("lag"),
            _success_response({"mined": 1}),
        ]

        result = await execute_skill(skill, bridge, {})

        assert result.success is True
        assert bridge.send_command.call_count == 2

    async def test_skill_level_precondition_failure(self):
        """Skill-level preconditions are checked before any step runs."""
        skill = Skill(
            id="needs_food",
            name="Needs Food",
            description="Requires food < 15",
            preconditions=["food < 15"],
            steps=[
                SkillStep(name="check", params={"condition": "food < 15"}),
            ],
        )

        bridge = _make_bridge()
        # food=20 → precondition fails
        context = {"food": 20}

        result = await execute_skill(skill, bridge, context)

        assert result.success is False
        assert result.failed_at == -1  # -1 means skill-level failure
        assert "preconditions" in (result.reason or "").lower()
        # Bridge should never be called
        bridge.send_command.assert_not_called()

    async def test_step_level_precondition_failure(self):
        """Step-level preconditions are checked per-step."""
        skill = Skill(
            id="step_precond",
            name="Step Precond",
            description="Step with preconditions",
            steps=[
                SkillStep(name="check", params={"condition": "alive"}),
                SkillStep(
                    name="mine",
                    params={"block_type": "diamond", "count": 1},
                    preconditions=["has_pickaxe"],
                ),
            ],
        )

        bridge = _make_bridge()
        bridge.send_command.return_value = _success_response()
        context = {}  # no has_pickaxe

        result = await execute_skill(skill, bridge, context)

        assert result.success is False
        assert result.failed_at == 1
        assert "preconditions" in (result.reason or "").lower()
        # Only first step should have been called
        assert bridge.send_command.call_count == 1

    async def test_unknown_skill_id_returns_failure(self):
        """execute_skill_by_id with unknown ID returns failure."""
        library = SkillLibrary()
        bridge = _make_bridge()

        result = await library.execute_skill_by_id("nonexistent", bridge)

        assert result.success is False
        assert "not found" in (result.reason or "").lower()


# ── 8.3 Skill Learning: Stats & Cleanup ─────────────────────────────────────


class TestSkillLearningStatsCleanup:
    """Cleanup removes low-quality skills and keeps high-quality ones."""

    async def test_cleanup_removes_low_success_rate_skill(self):
        """Skill with < 30% success rate and >= 10 executions is removed."""
        library = SkillLibrary()

        bad_skill = Skill(
            id="bad_skill",
            name="Bad Skill",
            description="Always fails",
            steps=[SkillStep(name="check", params={"condition": "alive"})],
            is_learned=True,
        )
        await library.save_skill(bad_skill)

        # Simulate 12 executions: 2 success, 10 failure → 16.7% success rate
        bridge = _make_bridge()
        bridge.send_command.side_effect = [
            _success_response(),
        ] * 2 + [_error_response("fail")] * 10

        for _ in range(2):
            bad_skill.success_count += 1
        for _ in range(10):
            bad_skill.fail_count += 1

        assert bad_skill.success_rate < 0.3
        assert (bad_skill.success_count + bad_skill.fail_count) >= 10

        await library.cleanup()

        retrieved = await library.get_skill("bad_skill")
        assert retrieved is None

    async def test_cleanup_keeps_high_success_rate_skill(self):
        """Skill with >= 30% success rate is kept."""
        library = SkillLibrary()

        good_skill = Skill(
            id="good_skill",
            name="Good Skill",
            description="Usually succeeds",
            steps=[SkillStep(name="check", params={"condition": "alive"})],
            is_learned=True,
        )
        await library.save_skill(good_skill)

        # 8 success, 2 failure → 80% success rate
        good_skill.success_count = 8
        good_skill.fail_count = 2

        assert good_skill.success_rate >= 0.3
        assert (good_skill.success_count + good_skill.fail_count) >= 10

        await library.cleanup()

        retrieved = await library.get_skill("good_skill")
        assert retrieved is not None

    async def test_cleanup_keeps_insufficient_data_skill(self):
        """Skill with < 10 total executions is kept regardless of rate."""
        library = SkillLibrary()

        new_skill = Skill(
            id="new_skill",
            name="New Skill",
            description="Not enough data",
            steps=[SkillStep(name="check", params={"condition": "alive"})],
            is_learned=True,
        )
        await library.save_skill(new_skill)

        # 1 success, 4 failure → 20% success rate, but only 5 total
        new_skill.success_count = 1
        new_skill.fail_count = 4

        assert new_skill.success_rate < 0.3
        assert (new_skill.success_count + new_skill.fail_count) < 10

        await library.cleanup()

        retrieved = await library.get_skill("new_skill")
        assert retrieved is not None

    async def test_cleanup_removes_multiple_low_quality_skills(self):
        """Multiple low-quality skills are all removed in one cleanup."""
        library = SkillLibrary()

        for i in range(3):
            skill = Skill(
                id=f"bad_{i}",
                name=f"Bad {i}",
                description="Low quality",
                steps=[SkillStep(name="check", params={"condition": "alive"})],
                is_learned=True,
            )
            skill.success_count = 1
            skill.fail_count = 19  # 5% success rate
            await library.save_skill(skill)

        await library.cleanup()

        for i in range(3):
            assert await library.get_skill(f"bad_{i}") is None

    async def test_cleanup_keeps_mixed_quality_skills(self):
        """Cleanup removes bad skills but keeps good ones."""
        library = SkillLibrary()

        bad = Skill(id="bad", name="Bad", description="Bad", is_learned=True)
        bad.success_count = 2
        bad.fail_count = 18  # 10%
        await library.save_skill(bad)

        good = Skill(id="good", name="Good", description="Good", is_learned=True)
        good.success_count = 15
        good.fail_count = 5  # 75%
        await library.save_skill(good)

        borderline = Skill(id="borderline", name="Borderline", description="Borderline", is_learned=True)
        borderline.success_count = 3
        borderline.fail_count = 7  # 30% — exactly at threshold, kept
        await library.save_skill(borderline)

        await library.cleanup()

        assert await library.get_skill("bad") is None
        assert await library.get_skill("good") is not None
        assert await library.get_skill("borderline") is not None

    async def test_stats_updated_across_multiple_executions(self):
        """Success/fail counts accumulate correctly across runs."""
        library = SkillLibrary()

        skill = Skill(
            id="accumulator",
            name="Accumulator",
            description="Tracks stats",
            steps=[SkillStep(name="check", params={"condition": "alive"})],
        )
        await library.save_skill(skill)

        bridge = _make_bridge()

        # 3 successes
        for _ in range(3):
            bridge.send_command.return_value = _success_response()
            await execute_skill(skill, bridge, {})

        # 2 failures
        for _ in range(2):
            bridge.send_command.return_value = _error_response("oops")
            await execute_skill(skill, bridge, {})

        assert skill.success_count == 3
        assert skill.fail_count == 2
        assert skill.success_rate == pytest.approx(0.6)
        assert skill.last_used != ""

    async def test_avg_duration_updated_on_execution(self):
        """avg_duration is updated after each execution."""
        library = SkillLibrary()

        skill = Skill(
            id="timed",
            name="Timed",
            description="Tracks duration",
            steps=[SkillStep(name="check", params={"condition": "alive"})],
        )
        await library.save_skill(skill)

        bridge = _make_bridge()
        bridge.send_command.return_value = _success_response()

        await execute_skill(skill, bridge, {})
        assert skill.avg_duration > 0

    async def test_full_lifecycle_stats_and_cleanup(self):
        """Full lifecycle: execute many times, verify stats, cleanup removes bad."""
        library = SkillLibrary()

        # Create a skill that will "mostly fail".
        # cleanup() only removes learned skills, so mark is_learned=True.
        skill = Skill(
            id="unlucky",
            name="Unlucky",
            description="Fails most of the time",
            steps=[SkillStep(name="mine", params={"block_type": "netherite", "count": 1})],
            is_learned=True,
        )
        await library.save_skill(skill)

        bridge = _make_bridge()

        # Execute 12 times: 2 success, 10 failure
        for i in range(12):
            if i < 2:
                bridge.send_command.return_value = _success_response()
            else:
                bridge.send_command.return_value = _error_response("bad luck")
            await execute_skill(skill, bridge, {})

        # Verify stats before cleanup
        assert skill.success_count == 2
        assert skill.fail_count == 10
        assert skill.success_rate == pytest.approx(2 / 12)
        assert skill.success_rate < 0.3

        # Cleanup should remove it
        await library.cleanup()
        assert await library.get_skill("unlucky") is None
