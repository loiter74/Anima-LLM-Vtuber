"""Tests for survival_runner.py — mock bridge integration tests."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from animetta.tools.minecraft.survival.models import SurvivalPhase
from animetta.tools.minecraft.survival.runner import SurvivalIronRunner


class MockBridge:
    """A mock MinecraftBridge that simulates command responses."""

    def __init__(self):
        self.is_running = True
        self._call_log: list[tuple[str, dict | None]] = []
        self._responses: dict[str, Any] = {}
        self._sequence_responses: dict[str, list[Any]] = {}
        self._sequence_indices: dict[str, int] = {}

    def set_response(self, action: str, response: Any) -> None:
        self._responses[action] = response

    def set_sequence(self, action: str, responses: list[Any]) -> None:
        self._sequence_responses[action] = responses
        self._sequence_indices[action] = 0

    async def send_command(
        self, action: str, params: dict | None = None, timeout: float = 60.0
    ) -> dict:
        self._call_log.append((action, params))

        # Check for sequence responses first
        if action in self._sequence_responses:
            seq = self._sequence_responses[action]
            idx = self._sequence_indices[action]
            self._sequence_indices[action] = (idx + 1) % len(seq)
            return seq[idx]

        if action in self._responses:
            return self._responses[action]

        return {"status": "success", "result": f"mock {action}"}


def _default_status_response():
    return {
        "status": "success",
        "result": {
            "position": {"x": 100.0, "y": 64.0, "z": 200.0},
            "health": 20.0,
            "food": 20.0,
            "dimension": "overworld",
            "game_mode": "survival",
            "weather": "clear",
            "time": "morning",
            "biome": "plains",
            "inventory": {},
            "nearby_entities": {},
            "current_goal": None,
        },
    }


class TestSurvivalIronRunnerHappyPath:
    def test_full_run_empty_to_complete(self):
        """Mock full run: all phases succeed, final inventory has iron gear."""
        bridge = MockBridge()

        # All collect/craft/smelts succeed
        success = {"status": "success", "result": "done"}
        bridge.set_response("collect", success)
        bridge.set_response("craft", success)
        bridge.set_response("smelt", success)

        # Status returns iron gear at the end
        final_status = {
            "status": "success",
            "result": {
                "position": {"x": 100, "y": 64, "z": 200},
                "health": 18.0,
                "food": 16.0,
                "inventory": {
                    "iron_pickaxe": 1,
                    "iron_sword": 1,
                    "iron_chestplate": 1,
                    "crafting_table": 1,
                    "furnace": 1,
                },
                "nearby_entities": {},
            },
        }
        bridge.set_response("status", final_status)

        runner = SurvivalIronRunner(bridge)
        report = asyncio.new_event_loop().run_until_complete(runner.run())

        assert report.completed is True
        assert report.current_phase == SurvivalPhase.IRON_GEAR
        assert len(report.phase_results) > 0
        # All phases should have succeeded
        for pr in report.phase_results:
            assert pr.success is True, f"Phase {pr.phase.value} failed: {pr.failure_message}"

    def test_status_called_multiple_times(self):
        """Status is called for safety checks and final inventory."""
        bridge = MockBridge()
        bridge.set_response("collect", {"status": "success", "result": "Collected 3 oak_log"})
        bridge.set_response("craft", {"status": "success", "result": "Crafted 1 crafting_table"})
        bridge.set_response(
            "smelt", {"status": "success", "result": "Smelting 3 raw_iron with coal"}
        )
        bridge.set_response("status", _default_status_response())

        runner = SurvivalIronRunner(bridge)
        asyncio.new_event_loop().run_until_complete(runner.run())

        status_calls = [c for c in bridge._call_log if c[0] == "status"]
        assert len(status_calls) >= 2  # At least safety pre-check + final


class TestSurvivalIronRunnerFailures:
    def test_collect_failure_recovery(self):
        """When collect fails on first try, recovery should kick in."""
        bridge = MockBridge()

        # First collect fails, second succeeds
        bridge.set_sequence(
            "collect",
            [
                {"status": "error", "result": "No more oak_log nearby, collected 0"},
                {"status": "success", "result": "Collected 3 oak_log"},
            ],
        )
        bridge.set_response("craft", {"status": "success", "result": "Crafted"})
        bridge.set_response("smelt", {"status": "success", "result": "Smelting"})
        bridge.set_response("status", _default_status_response())

        runner = SurvivalIronRunner(bridge)
        asyncio.new_event_loop().run_until_complete(runner.run())

        # Should have retried collect
        collect_calls = [c for c in bridge._call_log if c[0] == "collect"]
        assert len(collect_calls) >= 2

    def test_bridge_not_running(self):
        """If bridge is not running, runner should return incomplete report."""
        bridge = MockBridge()
        bridge.is_running = False

        runner = SurvivalIronRunner(bridge)
        report = asyncio.new_event_loop().run_until_complete(runner.run())

        assert report.completed is False

    def test_bridge_returns_none(self):
        """If bridge.send_command returns None (exception), handle gracefully."""
        bridge = AsyncMock()
        bridge.is_running = True
        bridge.send_command = AsyncMock(return_value=None)

        runner = SurvivalIronRunner(bridge)
        report = asyncio.new_event_loop().run_until_complete(runner.run())

        assert report.completed is False


class TestSurvivalIronRunnerInterrupt:
    def test_interrupt_stops_run(self):
        """Calling interrupt() should stop the runner after current phase."""
        bridge = MockBridge()
        bridge.set_response("collect", {"status": "success", "result": "ok"})
        bridge.set_response("craft", {"status": "success", "result": "ok"})
        bridge.set_response("smelt", {"status": "success", "result": "ok"})
        bridge.set_response("status", _default_status_response())

        runner = SurvivalIronRunner(bridge)

        # Interrupt after first phase
        original_run_phase = runner._run_phase

        async def run_phase_with_interrupt(phase, report):
            result = await original_run_phase(phase, report)
            runner.interrupt()
            return result

        runner._run_phase = run_phase_with_interrupt
        report = asyncio.new_event_loop().run_until_complete(runner.run())

        # Should have stopped early
        assert len(report.phase_results) <= 2


class TestSurvivalIronRunnerSummary:
    def test_report_summary_format(self):
        """Report summary should have expected keys."""
        bridge = MockBridge()
        bridge.set_response("collect", {"status": "success", "result": "ok"})
        bridge.set_response("craft", {"status": "success", "result": "ok"})
        bridge.set_response("smelt", {"status": "success", "result": "ok"})
        bridge.set_response(
            "status",
            {
                "status": "success",
                "result": {
                    "inventory": {"iron_pickaxe": 1, "iron_sword": 1, "iron_chestplate": 1},
                    "health": 20.0,
                    "food": 18.0,
                    "nearby_entities": {},
                },
            },
        )

        runner = SurvivalIronRunner(bridge)
        report = asyncio.new_event_loop().run_until_complete(runner.run())

        s = report.summary()
        assert "completed" in s
        assert "elapsed_seconds" in s
        assert "phase_summary" in s
        assert isinstance(s["phase_summary"], list)
