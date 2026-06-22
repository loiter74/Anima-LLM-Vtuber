from __future__ import annotations

from animetta.tools.minecraft.core.bridge import MinecraftBridge

"""Tests for MinecraftBridge — subprocess lifecycle and JSON-RPC communication."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Fixtures ──

@pytest.fixture
def mock_config():
    """Create a mock MinecraftConfig."""
    cfg = MagicMock()
    cfg.bot.host = "localhost"
    cfg.bot.port = 25565
    cfg.bot.username = "TestBot"
    return cfg


@pytest.fixture
def mock_process():
    """Create a mock asyncio subprocess process."""
    proc = MagicMock()
    proc.pid = 12345
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = AsyncMock(return_value=b"")
    proc.stderr = MagicMock()
    proc.stderr.readline = AsyncMock(return_value=b"")
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


async def _complete_ready_wait(awaitable, timeout):  # noqa: ARG001
    awaitable.close()
    return None


async def _timeout_ready_wait(awaitable, timeout):  # noqa: ARG001
    awaitable.close()
    raise TimeoutError()


# ── Test Classes ──

class TestMinecraftBridgeInit:
    """Bridge construction and initial state tests."""

    def test_initial_state_not_running(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        assert bridge.is_running is False
        assert bridge._process is None
        assert bridge._pending == {}
        assert bridge._next_id == 1

    def test_autonomous_flag_is_stored(self, mock_config):
        bridge = MinecraftBridge(mock_config, autonomous=True)
        assert bridge._autonomous_enabled is True

    def test_autonomous_flag_defaults_false(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        assert bridge._autonomous_enabled is False


class TestMinecraftBridgeStart:
    """Bridge.start() lifecycle tests."""

    async def test_start_script_not_found_returns_false(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        with patch("os.path.exists", return_value=False):
            result = await bridge.start()
        assert result is False
        assert bridge.is_running is False

    async def test_start_node_modules_missing_returns_false(self, mock_config):
        bridge = MinecraftBridge(mock_config)

        def exists_side_effect(path):
            if "index.js" in path:
                return True
            if "node_modules" in path:
                return False
            return False

        with patch("os.path.exists", side_effect=exists_side_effect):
            result = await bridge.start()
        assert result is False
        assert bridge.is_running is False

    async def test_start_already_running_returns_true(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        result = await bridge.start()
        assert result is True

    @patch("animetta.tools.minecraft.core.core.bridge.is_service_available", return_value=True)
    async def test_start_successful(self, mock_is_available, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)), \
             patch("asyncio.wait_for", side_effect=_complete_ready_wait):
            result = await bridge.start()

        assert result is True
        assert bridge.is_running is True
        assert bridge._process is mock_process

    @patch("animetta.tools.minecraft.core.core.bridge.is_service_available", return_value=True)
    async def test_start_login_timeout_still_succeeds(self, mock_is_available, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)), \
             patch("asyncio.wait_for", side_effect=_timeout_ready_wait):
            result = await bridge.start()

        assert result is True
        assert bridge.is_running is True

    async def test_start_exception_returns_false(self, mock_config):
        bridge = MinecraftBridge(mock_config)

        with patch("os.path.exists", return_value=True), \
             patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("spawn failed")):
            result = await bridge.start()

        assert result is False
        assert bridge.is_running is False

    async def test_start_with_autonomous_loop(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config, autonomous=True)

        mock_loop = MagicMock()
        mock_loop.start = AsyncMock()

        with patch("animetta.tools.minecraft.core.core.bridge.is_service_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)), \
             patch("asyncio.wait_for", side_effect=_complete_ready_wait), \
             patch("animetta.tools.minecraft.autonomous.loop.loop.AutonomousLoop", return_value=mock_loop):
            result = await bridge.start()

        assert result is True
        mock_loop.start.assert_awaited_once()


class TestMinecraftBridgeSendCommand:
    """Bridge.send_command() tests."""

    async def test_send_command_bridge_not_running(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        result = await bridge.send_command("status")
        assert result["status"] == "error"
        assert "not running" in result["result"]

    async def test_send_command_process_exited(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process
        mock_process.returncode = 1  # exited
        result = await bridge.send_command("status")
        assert result["status"] == "error"
        assert "exited" in result["result"]

    async def test_send_command_success(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        async def resolve_future(future, timeout):
            future.set_result({"status": "success", "result": "ok"})
            return await future

        with patch("asyncio.wait_for", side_effect=resolve_future):
            result = await bridge.send_command("goto", {"x": 0, "y": 64, "z": 0})

        assert result["status"] == "success"
        assert result["result"] == "ok"
        # Verify JSON was written to stdin
        mock_process.stdin.write.assert_called_once()
        written = mock_process.stdin.write.call_args[0][0]
        decoded = json.loads(written.decode("utf-8").strip())
        assert decoded["action"] == "goto"
        assert decoded["params"] == {"x": 0, "y": 64, "z": 0}

    async def test_send_command_timeout(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await bridge.send_command("goto", timeout=0.1)

        assert result["status"] == "error"
        assert "timed out" in result["result"]

    async def test_send_command_exception(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        with patch("asyncio.wait_for", side_effect=ValueError("bad data")):
            result = await bridge.send_command("goto")

        assert result["status"] == "error"
        assert "bad data" in result["result"]

    async def test_send_command_increments_id(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process
        assert bridge._next_id == 1

        async def resolve_future(future, timeout):
            future.set_result({"status": "ok"})
            return await future

        with patch("asyncio.wait_for", side_effect=resolve_future):
            await bridge.send_command("cmd1")
        assert bridge._next_id == 2

        with patch("asyncio.wait_for", side_effect=resolve_future):
            await bridge.send_command("cmd2")
        assert bridge._next_id == 3


class TestMinecraftBridgeReadStdout:
    """Bridge._read_stdout() JSON-RPC parsing tests."""

    async def test_read_stdout_parses_response(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        future = asyncio.get_event_loop().create_future()
        bridge._pending[1] = future

        line = json.dumps({"id": 1, "status": "success", "result": "done"}).encode("utf-8") + b"\n"
        mock_process.stdout.readline = AsyncMock(side_effect=[
            line,
            b"",  # EOF → stops loop
        ])

        await bridge._read_stdout()
        assert future.done()
        assert future.result() == {"status": "success", "result": "done"}

    async def test_read_stdout_handles_invalid_json(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        mock_process.stdout.readline = AsyncMock(side_effect=[
            b"not json\n",
            b"",  # EOF
        ])

        # Should not crash on invalid JSON
        await bridge._read_stdout()

    async def test_read_stdout_login_event_sets_ready(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        line = json.dumps({
            "id": None, "status": "event",
            "result": {"type": "login", "username": "AnimaBot"}
        }).encode("utf-8") + b"\n"

        mock_process.stdout.readline = AsyncMock(side_effect=[line, b""])

        await bridge._read_stdout()
        assert bridge._bot_ready.is_set()

    async def test_read_stdout_handles_cancellation(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        mock_process.stdout.readline = AsyncMock(side_effect=asyncio.CancelledError)

        await bridge._read_stdout()
        assert bridge.is_running is False

    async def test_read_stdout_unhandled_id_not_crash(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        line = json.dumps({"id": 999, "status": "success", "result": "orphan"}).encode("utf-8") + b"\n"
        mock_process.stdout.readline = AsyncMock(side_effect=[line, b""])

        await bridge._read_stdout()
        # Should not raise any error


class TestMinecraftBridgeStop:
    """Bridge.stop() shutdown tests."""

    async def test_stop_terminates_process(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        await bridge.stop()

        mock_process.terminate.assert_called_once()
        assert bridge.is_running is False

    async def test_stop_resolves_pending_futures(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        future = asyncio.get_event_loop().create_future()
        bridge._pending[7] = future

        await bridge.stop()

        assert future.done()
        assert future.result()["status"] == "error"
        assert "stopped" in future.result()["result"]
        assert len(bridge._pending) == 0

    async def test_stop_terminate_timeout_falls_back_to_kill(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        # First wait() raises TimeoutError (inside asyncio.wait_for in try block),
        # second wait() succeeds (after kill in except block)
        mock_process.wait.side_effect = [asyncio.TimeoutError, None]

        await bridge.stop()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()

    async def test_stop_process_already_gone(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        mock_process.terminate.side_effect = ProcessLookupError

        await bridge.stop()
        # Should not raise
        assert bridge.is_running is False


class TestMinecraftBridgeModeCommands:
    """Bridge mode command tests (set_planner_mode, set_rule_mode, get_plan_status)."""

    async def test_set_planner_mode(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        async def resolve_future(future, timeout):
            future.set_result({"status": "success", "result": "mode set"})
            return await future

        with patch("asyncio.wait_for", side_effect=resolve_future):
            result = await bridge.set_planner_mode([{"action": "goto", "params": {"x": 0, "y": 64, "z": 0}}])

        assert result["status"] == "success"

    async def test_set_rule_mode(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        async def resolve_future(future, timeout):
            future.set_result({"status": "success", "result": "mode set"})
            return await future

        with patch("asyncio.wait_for", side_effect=resolve_future):
            result = await bridge.set_rule_mode()

        assert result["status"] == "success"

    async def test_get_plan_status(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        async def resolve_future(future, timeout):
            future.set_result({"status": "success", "result": {"current_step": 2, "total": 5}})
            return await future

        with patch("asyncio.wait_for", side_effect=resolve_future):
            result = await bridge.get_plan_status()

        assert result["result"] == {"current_step": 2, "total": 5}


class TestMinecraftBridgePauseResumeAutonomous:
    """Bridge pause_autonomous / resume_autonomous tests."""

    def test_pause_autonomous_no_loop_does_not_crash(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        bridge._autonomous_loop = None
        bridge.pause_autonomous()  # Should not raise

    def test_resume_autonomous_no_loop_does_not_crash(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        bridge._autonomous_loop = None
        bridge.resume_autonomous()  # Should not raise

    def test_pause_delegates_to_loop(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        mock_loop = MagicMock()
        bridge._autonomous_loop = mock_loop
        bridge.pause_autonomous()
        mock_loop.pause.assert_called_once()

    def test_resume_delegates_to_loop(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        mock_loop = MagicMock()
        bridge._autonomous_loop = mock_loop
        bridge.resume_autonomous()
        mock_loop.resume.assert_called_once()
