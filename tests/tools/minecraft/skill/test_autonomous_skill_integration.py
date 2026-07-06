"""
Integration tests for AutonomousLoop + SkillLibrary.

Verifies that the autonomous loop correctly uses the SkillLibrary
for skill matching and execution during its evaluation cycle.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from animetta.tools.minecraft.autonomous.loop import AutonomousLoop
from animetta.tools.minecraft.autonomous.rules_engine import RulesEngine
from animetta.tools.minecraft.other.world_state import WorldState
from animetta.tools.minecraft.skill.library import Skill, SkillLibrary, SkillResult

# ── Helpers ──


def _status_response(
    x: float = 0, y: float = 64, z: float = 0,
    health: float = 20.0, food: float = 20.0,
    time_of_day: str = "day", weather: str = "clear",
    inventory: dict | None = None,
    nearby_entities: dict | None = None,
) -> dict:
    """Build a realistic mc_status() response dict."""
    return {
        "status": "success",
        "result": {
            "position": {"x": x, "y": y, "z": z},
            "health": health,
            "food": food,
            "time": time_of_day,
            "weather": weather,
            "biome": "plains",
            "dimension": "overworld",
            "game_mode": "survival",
            "inventory": inventory or {},
            "nearby_entities": nearby_entities or {},
        },
    }


def _make_skill(skill_id: str = "test_skill", preconditions: list[str] | None = None) -> Skill:
    """Create a minimal test skill."""
    from animetta.tools.minecraft.skill.library import SkillStep

    return Skill(
        id=skill_id,
        name="Test Skill",
        description="A test skill",
        category="test",
        preconditions=preconditions or [],
        steps=[
            SkillStep(name="check", params={"condition": "health > 6"}),
        ],
        tags=["test"],
    )


def _make_bridge(status_response: dict | None = None) -> MagicMock:
    """Create a mock bridge with configurable status response."""
    bridge = MagicMock()
    bridge.send_command = AsyncMock(
        return_value=status_response or _status_response()
    )
    return bridge


def _make_rules() -> RulesEngine:
    """Create a minimal RulesEngine (no file needed)."""
    rules = MagicMock(spec=RulesEngine)
    rules.rules = MagicMock()
    rules.rules.character_name = "TestBot"
    rules.rules.building = None
    rules.auto_heal_threshold = 10
    rules.return_to_base_at_night = True
    rules.proactive_chat_chance = 0.0
    rules.chat_cooldown = 60.0
    rules.get_chat_message = MagicMock(return_value=None)
    return rules


# ── Tests ──


class TestAutonomousWithSkillLibrary:
    """AutonomousLoop stores and exposes the SkillLibrary."""

    def test_autonomous_with_skill_library(self) -> None:
        """SkillLibrary injected via constructor is stored."""
        bridge = _make_bridge()
        lib = SkillLibrary()
        loop = AutonomousLoop(bridge, rules=_make_rules(), skill_library=lib)

        assert loop._skill_library is lib

    def test_autonomous_without_skill_library(self) -> None:
        """None skill_library is fine — loop still works."""
        bridge = _make_bridge()
        loop = AutonomousLoop(bridge, rules=_make_rules())

        assert loop._skill_library is None


class TestEvaluateMatchesSkill:
    """_evaluate returns execute_skill when SkillLibrary matches."""

    async def test_evaluate_matches_skill(self) -> None:
        """When match_skills returns a skill, _evaluate returns ('execute_skill', ...)."""
        bridge = _make_bridge()
        lib = SkillLibrary()
        skill = _make_skill("survival_food")
        # Save skill so match_skills can find it
        await lib.save_skill(skill)

        # Make match_skills return the skill (preconditions satisfied)
        loop = AutonomousLoop(bridge, rules=_make_rules(), skill_library=lib)

        state = WorldState(
            health=20.0, food=10.0,  # food < 15 → matches survival_food
            x=0, y=64, z=0,
        )

        action, params = await loop._evaluate(state)
        assert action == "execute_skill"
        assert params is not None
        assert params["skill_id"] == "survival_food"


class TestEvaluateNoMatchFallsBack:
    """_evaluate falls back to default logic when no skills match."""

    async def test_evaluate_no_match_falls_back(self) -> None:
        """When match_skills returns empty, _evaluate uses existing priority chain."""
        bridge = _make_bridge()
        lib = SkillLibrary()
        # No skills saved → match_skills returns []

        loop = AutonomousLoop(bridge, rules=_make_rules(), skill_library=lib)

        # High food, high health, day time → should fall through to explore or idle
        state = WorldState(
            health=20.0, food=20.0,
            x=0, y=64, z=0,
            time="day",
        )

        # Reset cooldown so explore can fire
        loop._cooldown.reset("explore")

        action, params = await loop._evaluate(state)
        # Should be explore (default fallback) or idle
        assert action in ("explore", "idle")
        assert action != "execute_skill"


class TestExecuteSkillAction:
    """_execute dispatches execute_skill to _execute_skill."""

    async def test_execute_skill_action(self) -> None:
        """_execute calls _execute_skill when action is 'execute_skill'."""
        bridge = _make_bridge()
        lib = SkillLibrary()
        skill = _make_skill("test_skill")
        await lib.save_skill(skill)

        loop = AutonomousLoop(bridge, rules=_make_rules(), skill_library=lib)

        # Mock execute_skill_by_id to avoid real execution
        lib.execute_skill_by_id = AsyncMock(
            return_value=SkillResult(success=True, skill_id="test_skill")
        )

        state = WorldState(health=20.0, food=20.0)
        await loop._execute("execute_skill", {"skill_id": "test_skill"}, state)

        lib.execute_skill_by_id.assert_awaited_once_with(
            "test_skill", bridge, {
                "health": 20.0,
                "food": 20.0,
                "is_day": state.is_day,
                "is_night": state.is_night,
                "inventory": state.inventory,
            }
        )

    async def test_execute_skill_failure_logged(self) -> None:
        """Failed skill execution is logged but doesn't raise."""
        bridge = _make_bridge()
        lib = SkillLibrary()
        skill = _make_skill("failing_skill")
        await lib.save_skill(skill)

        loop = AutonomousLoop(bridge, rules=_make_rules(), skill_library=lib)

        lib.execute_skill_by_id = AsyncMock(
            return_value=SkillResult(
                success=False, skill_id="failing_skill", reason="precondition failed"
            )
        )

        state = WorldState(health=20.0, food=20.0)
        # Should not raise
        await loop._execute("execute_skill", {"skill_id": "failing_skill"}, state)

    async def test_execute_skill_no_library(self) -> None:
        """_execute_skill with no library does nothing (no crash)."""
        bridge = _make_bridge()
        loop = AutonomousLoop(bridge, rules=_make_rules())  # no skill_library

        state = WorldState(health=20.0, food=20.0)
        # Should not raise even without a library
        await loop._execute("execute_skill", {"skill_id": "missing"}, state)
