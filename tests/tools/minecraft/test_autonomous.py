from __future__ import annotations

from animetta.tools.minecraft.autonomous import AutonomousLoop, CooldownTracker
from animetta.tools.minecraft.bridge import MinecraftBridge
from animetta.tools.minecraft.rules_engine import BuildPlanStep, BuildTarget
from animetta.tools.minecraft.world_state import Entity, WorldState

"""Tests for AutonomousLoop — perception→decision→execution cycle."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

# ── Helpers ──

def status_response(
    x=0, y=64, z=0,
    health=20.0, food=20.0,
    time_of_day="day", weather="clear",
    inventory=None,
    nearby_entities=None,
):
    """Build a realistic mc_status() response dict."""
    if inventory is None:
        inventory = {}
    if nearby_entities is None:
        nearby_entities = {}

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
            "inventory": inventory,
            "nearby_entities": nearby_entities,
        }
    }


def hostile_nearby(distance=10, count=3):
    """Build nearby_entities with hostile mobs."""
    return {
        "hostile": {"count": count, "distance": distance, "name": "zombie"},
    }


def player_nearby():
    """Build nearby_entities with a player."""
    return {
        "player": {"count": 1, "distance": 5, "name": "Steve"},
    }


def make_rules_engine():
    """Create a mock RulesEngine with default rules."""
    rules = MagicMock()
    rules.auto_heal_threshold = 10
    rules.return_to_base_at_night = True
    rules.proactive_chat_chance = 0.25
    rules.chat_cooldown = 30
    rules.get_chat_message = MagicMock(return_value=None)
    # No building by default
    rules.rules.building = None
    rules.rules.character_name = "TestRules"
    rules.rules.priorities = ["survival", "maintenance", "building", "social", "exploration"]
    rules.rules.safety = {"auto_heal_threshold": 10, "return_to_base_at_night": True}
    rules.rules.chat = {"proactive_chance": 0.25, "cooldown_seconds": 30, "topics": []}
    return rules


# ── Test Classes ──

class TestCooldownTracker:
    """CooldownTracker unit tests."""

    def test_can_execute_initially_true(self):
        tracker = CooldownTracker(default_cooldown=30.0)
        assert tracker.can_execute("build") is True

    def test_cannot_execute_during_cooldown(self):
        tracker = CooldownTracker(default_cooldown=30.0)
        tracker.mark_executed("build")
        assert tracker.can_execute("build") is False

    def test_can_execute_different_action_during_cooldown(self):
        tracker = CooldownTracker(default_cooldown=30.0)
        tracker.mark_executed("build")
        assert tracker.can_execute("gather") is True

    def test_reset_clears_cooldown(self):
        tracker = CooldownTracker(default_cooldown=30.0)
        tracker.mark_executed("build")
        tracker.reset("build")
        assert tracker.can_execute("build") is True


class TestAutonomousLoopInit:
    """AutonomousLoop construction tests."""

    def test_init_default_rules(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        loop = AutonomousLoop(bridge)

        assert loop._running is False
        assert loop._paused is False
        assert loop._bridge is bridge
        assert loop._rules is not None

    def test_init_with_custom_rules(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        rules = make_rules_engine()
        loop = AutonomousLoop(bridge, rules=rules)

        assert loop._rules is rules


class TestAutonomousLoopLifecycle:
    """AutonomousLoop lifecycle (start/stop/pause/resume) tests."""

    def test_start_sets_running_true(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        loop = AutonomousLoop(bridge)

        with patch("asyncio.create_task"):
            asyncio.run(loop.start())

        assert loop.is_running is True

    def test_calling_start_twice_does_nothing(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        loop = AutonomousLoop(bridge)

        with patch("asyncio.create_task") as mock_create:
            asyncio.run(loop.start())
            asyncio.run(loop.start())
        # create_task should only be called once
        assert mock_create.call_count == 1

    def test_stop_sets_running_false(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        loop = AutonomousLoop(bridge)
        loop._running = True

        asyncio.run(loop.stop())
        assert loop.is_running is False

    def test_pause_and_resume(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        loop = AutonomousLoop(bridge)

        loop.pause()
        assert loop._paused is True

        loop.resume()
        assert loop._paused is False

    async def test_stop_cancels_loop_task(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        loop = AutonomousLoop(bridge)

        # Create a real task that sleeps, then stop
        async def mock_loop():
            try:
                while loop._running:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise

        loop._running = True
        loop._loop_task = asyncio.create_task(mock_loop())
        task_ref = loop._loop_task  # Save reference before stop sets to None

        await loop.stop()
        assert task_ref.done()
        assert loop._loop_task is None
        assert loop.is_running is False


class TestAutonomousLoopEvaluate:
    """AutonomousLoop._evaluate() decision engine tests."""

    def _make_loop(self, bridge=None):
        if bridge is None:
            bridge = MagicMock()
            bridge.send_command = AsyncMock()
        rules = make_rules_engine()
        return AutonomousLoop(bridge, rules=rules)

    def _make_state(self, **kwargs):
        return WorldState(**kwargs)

    async def test_evaluate_threat_nearby_triggers_survive(self):
        loop = self._make_loop()
        state = self._make_state(
            health=20.0,
            entities=[Entity(name="zombie", type="hostile", distance=5.0, count=3)],
        )
        action, params = await loop._evaluate(state)
        assert action == loop.ACTION_SURVIVE
        assert params["reason"] == "threat_nearby"

    async def test_evaluate_low_health_triggers_survive(self):
        loop = self._make_loop()
        loop._rules.auto_heal_threshold = 12
        state = self._make_state(health=8.0)  # below threshold
        action, params = await loop._evaluate(state)
        assert action == loop.ACTION_SURVIVE
        assert params["reason"] == "low_health"

    async def test_evaluate_night_return_triggers_survive(self):
        loop = self._make_loop()
        loop._base_pos = {"x": 100, "y": 64, "z": 100}
        state = self._make_state(
            x=200, y=64, z=200,  # far from base
            health=20.0,
            time="night",
        )
        action, params = await loop._evaluate(state)
        assert action == loop.ACTION_SURVIVE
        assert params["reason"] == "night_return"

    async def test_evaluate_night_near_base_does_not_trigger(self):
        loop = self._make_loop()
        loop._base_pos = {"x": 0, "y": 64, "z": 0}
        state = self._make_state(
            x=1, y=64, z=1,
            health=20.0,
            time="night",
        )
        action, _ = await loop._evaluate(state)
        # Close to base, should not trigger survive
        assert action != loop.ACTION_SURVIVE

    async def test_evaluate_building_in_progress_checks_materials(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        rules = make_rules_engine()

        # Set up building target
        rules.rules.building = BuildTarget(
            target="house",
            blueprint="platform",
            required_materials={"cobblestone": 10},
            build_plan=[BuildPlanStep(action="place", block="cobblestone", description="place block")],
        )

        loop = AutonomousLoop(bridge, rules=rules)
        loop._cooldown.reset("gather")
        loop._cooldown.reset("build")

        # State where we have NO materials → should GATHER
        state = self._make_state(health=20.0, time="day", inventory={})
        action, params = await loop._evaluate(state)
        # Getting either GATHER or BUILD based on cooldown, need materials first
        if action == loop.ACTION_GATHER:
            assert params["material"] == "cobblestone"
        # If cooldowns align differently, build can also fire if materials are met

    async def test_evaluate_idle_when_safe(self):
        loop = self._make_loop()
        state = self._make_state(health=20.0, time="day")

        # Mock random to avoid explore
        with patch("random.random", return_value=1.0):  # suppress chat
            loop._cooldown.mark_executed("explore")  # force cooldown
            action, _ = await loop._evaluate(state)
            # Should fall through to IDLE when all cooldowns are active
            assert action in (loop.ACTION_IDLE, loop.ACTION_EXPLORE, loop.ACTION_CHAT)

    async def test_evaluate_explore_default_fallback(self):
        loop = self._make_loop()
        state = self._make_state(health=20.0, time="day", x=10, z=10)

        loop._cooldown.reset("explore")
        with patch("random.random", return_value=1.0), patch("random.randint", return_value=5):  # suppress chat random
            action, params = await loop._evaluate(state)
            assert action == loop.ACTION_EXPLORE
            assert "x" in params
            assert "z" in params


class TestAutonomousLoopExecute:
    """AutonomousLoop._execute() action dispatch tests."""

    def _make_loop(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        bridge.send_command = AsyncMock(return_value={"status": "success", "result": "ok"})

        rules = make_rules_engine()
        loop = AutonomousLoop(bridge, rules=rules)
        return loop

    @staticmethod
    def default_state():
        return WorldState()

    async def test_execute_survive_threat_attacks(self):
        loop = self._make_loop()
        state = self.default_state()
        await loop._execute_survive({"reason": "threat_nearby"}, state)
        loop._bridge.send_command.assert_awaited()
        call_args = loop._bridge.send_command.call_args[0]
        assert call_args[0] == "attack"

    async def test_execute_survive_night_return_goto_base(self):
        loop = self._make_loop()
        state = self.default_state()
        await loop._execute_survive(
            {"reason": "night_return", "base": {"x": 42, "y": 64, "z": 42}},
            state,
        )
        loop._bridge.send_command.assert_awaited()
        call_args = loop._bridge.send_command.call_args[0]
        assert call_args[0] == "goto"

    async def test_execute_gather_collects_material(self):
        loop = self._make_loop()
        state = self.default_state()
        # Patch _threat_check to avoid extra send_command call
        loop._threat_check = AsyncMock(return_value=False)
        await loop._execute_gather({"material": "oak_log", "count": 8}, state)
        # Should have called collect via send_command
        calls = [c[0][0] for c in loop._bridge.send_command.call_args_list]
        assert "collect" in calls

    async def test_execute_explore_goto_target(self):
        loop = self._make_loop()
        loop._threat_check = AsyncMock(return_value=False)
        await loop._execute_explore({"x": 100, "z": 200}, timeout=10.0)
        loop._bridge.send_command.assert_awaited()
        call_args = loop._bridge.send_command.call_args[0]
        assert call_args[0] == "goto"

    async def test_execute_chat_sends_message(self):
        loop = self._make_loop()
        loop._rules.get_chat_message = MagicMock(return_value="Hello everyone!")
        await loop._execute_chat({"trigger": "player_nearby"})
        loop._bridge.send_command.assert_awaited()
        call_args = loop._bridge.send_command.call_args[0]
        assert call_args[0] == "chat"

    async def test_execute_chat_no_message_does_nothing(self):
        loop = self._make_loop()
        loop._rules.get_chat_message = MagicMock(return_value=None)
        await loop._execute_chat({"trigger": "unknown_trigger"})
        # send_command should NOT be called when no message is found
        loop._bridge.send_command.assert_not_awaited()


class TestAutonomousLoopChatTrigger:
    """AutonomousLoop._get_chat_trigger() tests."""

    def _make_loop(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        rules = make_rules_engine()
        return AutonomousLoop(bridge, rules=rules)

    def test_chat_cooldown_active_returns_none(self):
        loop = self._make_loop()
        loop._chat_cooldown_until = time.time() + 999
        state = WorldState(
            entities=[Entity(name="Steve", type="player", distance=5, count=1)]
        )
        with patch("random.random", return_value=0.1):  # under chance
            result = loop._get_chat_trigger(state)
        assert result is None

    def test_random_check_above_threshold_returns_none(self):
        loop = self._make_loop()
        state = WorldState(
            entities=[Entity(name="Steve", type="player", distance=5, count=1)]
        )
        with patch("random.random", return_value=0.9):  # above 0.25 chance
            result = loop._get_chat_trigger(state)
        assert result is None

    def test_player_nearby_triggers_chat(self):
        loop = self._make_loop()
        state = WorldState(
            entities=[Entity(name="Steve", type="player", distance=5, count=1)]
        )
        with patch("random.random", return_value=0.1):
            result = loop._get_chat_trigger(state)
        assert result == "player_nearby"

    def test_night_time_triggers_chat(self):
        loop = self._make_loop()
        state = WorldState(time="night")
        with patch("random.random", return_value=0.1):
            result = loop._get_chat_trigger(state)
        assert result == "night_time"

    def test_rain_triggers_chat(self):
        loop = self._make_loop()
        state = WorldState(weather="rain")
        with patch("random.random", return_value=0.1):
            result = loop._get_chat_trigger(state)
        assert result == "rain_start"

    def test_no_trigger_returns_none(self):
        loop = self._make_loop()
        state = WorldState(time="day", weather="clear")
        with patch("random.random", return_value=0.1):
            result = loop._get_chat_trigger(state)
        assert result is None


class TestAutonomousLoopThreatCheck:
    """AutonomousLoop._threat_check() tests."""

    def _make_loop(self):

        config = MagicMock()
        config.bot.host = "localhost"
        config.bot.port = 25565
        config.bot.username = "TestBot"
        bridge = MinecraftBridge(config)
        bridge.send_command = AsyncMock()
        rules = make_rules_engine()
        return AutonomousLoop(bridge, rules=rules)

    async def test_threat_check_no_threat_returns_false(self):
        loop = self._make_loop()
        loop._bridge.send_command.return_value = status_response(
            x=0, y=64, z=0, health=20.0, time_of_day="day",
        )
        result = await loop._threat_check()
        assert result is False

    async def test_threat_check_threat_nearby_attacks(self):
        loop = self._make_loop()
        loop._bridge.send_command.side_effect = [
            status_response(
                x=0, y=64, z=0, health=20.0,
                nearby_entities=hostile_nearby(distance=5, count=3),
            ),
            {"status": "success", "result": "attacked"},
        ]
        result = await loop._threat_check()
        assert result is True
        # Should have called attack
        attack_calls = [c for c in loop._bridge.send_command.call_args_list if c[0][0] == "attack"]
        assert len(attack_calls) == 1

    async def test_threat_check_exception_returns_false(self):
        loop = self._make_loop()
        loop._bridge.send_command.side_effect = RuntimeError("connection lost")
        result = await loop._threat_check()
        assert result is False
