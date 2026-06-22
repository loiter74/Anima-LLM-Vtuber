"""
Tests for AutonomousLoop
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.tools.minecraft.autonomous.loop import AutonomousLoop, CooldownTracker


@pytest.fixture
def mock_bridge():
    bridge = AsyncMock()
    bridge.send_command = AsyncMock(return_value={
        "status": "success",
        "result": {
            "position": {"x": 100.0, "y": 65.0, "z": 200.0},
            "health": 20.0,
            "food": 18.0,
            "inventory": {},
            "nearby_entities": {},
            "time": "day",
            "weather": "clear"
        }
    })
    return bridge


@pytest.fixture
def mock_rules():
    rules = MagicMock()
    rules.auto_heal_threshold = 10
    rules.return_to_base_at_night = True
    rules.proactive_chat_chance = 0.1
    rules.rules = MagicMock()
    rules.rules.character_name = "TestBot"
    rules.rules.building = None
    rules.rules.chat = MagicMock()
    rules.rules.chat.proactive_chance = 0.1
    rules.rules.chat.cooldown_seconds = 60
    rules.rules.chat.topics = ["greeting"]
    return rules


@pytest.fixture
def autonomous(mock_bridge, mock_rules):
    return AutonomousLoop(mock_bridge, mock_rules)


class TestCooldownTracker:
    """Test cooldown tracking"""

    def test_can_execute_initially(self):
        """Can execute when no cooldown set"""
        tracker = CooldownTracker(default_cooldown=30.0)
        assert tracker.can_execute("test") is True

    def test_cooldown_active(self):
        """Cannot execute during cooldown"""
        tracker = CooldownTracker(default_cooldown=30.0)
        tracker.mark_executed("test")
        assert tracker.can_execute("test") is False

    def test_cooldown_expired(self):
        """Can execute after cooldown expires"""
        tracker = CooldownTracker(default_cooldown=0.0)
        tracker.mark_executed("test")
        assert tracker.can_execute("test") is True


class TestAutonomousLoop:
    """Test autonomous loop decisions"""

    def test_initialization(self, autonomous):
        """Loop initializes correctly"""
        assert autonomous.is_running is False
        assert autonomous._paused is False

    async def test_start_stop(self, autonomous):
        """Can start and stop loop"""
        await autonomous.start()
        assert autonomous.is_running is True
        await autonomous.stop()
        assert autonomous.is_running is False

    def test_pause_resume(self, autonomous):
        """Can pause and resume"""
        autonomous.pause()
        assert autonomous._paused is True
        autonomous.resume()
        assert autonomous._paused is False


class TestEvaluation:
    """Test decision evaluation"""

    async def test_survive_on_threat(self, autonomous):
        """Returns SURVIVE when threat nearby"""
        state = MagicMock()
        state.get_threat_level.return_value = 2
        state.nearest_threat_distance = 10
        state.health = 20
        state.is_night = False

        action, params = await autonomous._evaluate(state)
        assert action == AutonomousLoop.ACTION_SURVIVE
        assert params["reason"] == "threat_nearby"

    async def test_survive_on_low_health(self, autonomous):
        """Returns SURVIVE when health low"""
        state = MagicMock()
        state.get_threat_level.return_value = 0
        state.health = 5  # Below threshold of 10
        state.is_night = False

        action, params = await autonomous._evaluate(state)
        assert action == AutonomousLoop.ACTION_SURVIVE
        assert params["reason"] == "low_health"

    async def test_explore_when_idle(self, autonomous):
        """Returns EXPLORE when nothing else to do"""
        state = MagicMock()
        state.get_threat_level.return_value = 0
        state.health = 20
        state.is_night = False
        state.is_raining = False
        state.player_count = 0
        state.x = 100
        state.z = 200

        action, params = await autonomous._evaluate(state)
        # Should be EXPLORE or IDLE depending on cooldown
        assert action in [AutonomousLoop.ACTION_EXPLORE, AutonomousLoop.ACTION_IDLE]
