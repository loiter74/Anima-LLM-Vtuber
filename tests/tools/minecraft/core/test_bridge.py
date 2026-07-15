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
    cfg.bot.version = None
    cfg.runtime.runtime_path = ""  # default: resolves to voyager-mc-bot sibling
    cfg.runtime.entrypoint = "index.js"
    cfg.runtime.use_embedded_fallback = False
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

    def test_top_level_get_bridge_imports(self):
        from animetta.tools.minecraft import get_bridge

        assert callable(get_bridge)

    def test_core_tools_init_bridge_sets_core_bridge_singleton(self, mock_config):
        from animetta.tools.minecraft.core import bridge as bridge_module
        from animetta.tools.minecraft.core import tools as tools_module

        tools_module._bridge = None
        bridge_module._bridge = None

        try:
            with (
                patch(
                    "animetta.tools.minecraft.core.config.MinecraftConfig", return_value=mock_config
                ),
                patch("animetta.tools.minecraft.core.bridge.MinecraftBridge") as bridge_cls,
                patch("animetta.tools.minecraft.core.tools.asyncio.get_running_loop") as get_loop,
                patch("animetta.tools.minecraft.core.tools.asyncio.ensure_future"),
            ):
                mock_loop = MagicMock()
                mock_loop.is_running.return_value = True
                get_loop.return_value = mock_loop
                bridge_cls.return_value.start = AsyncMock()

                tools_module.init_bridge({"enabled": True})

            assert tools_module._bridge is bridge_cls.return_value
            assert bridge_module.get_bridge() is bridge_cls.return_value
        finally:
            tools_module._bridge = None
            bridge_module._bridge = None

    def test_initial_state_not_running(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        assert bridge.is_running is False
        assert bridge._process is None
        assert bridge._pending == {}
        assert bridge._next_id == 1

    def test_autonomous_flag_is_ignored_for_compatibility(self, mock_config):
        bridge = MinecraftBridge(mock_config, autonomous=True)
        assert not hasattr(bridge, "_autonomous_enabled")

    def test_bridge_has_no_autonomous_owner_by_default(self, mock_config):
        bridge = MinecraftBridge(mock_config)
        assert not hasattr(bridge, "_autonomous_loop")

    def test_resolve_bot_dir_keeps_invalid_configured_external_path(self, mock_config):
        mock_config.runtime.runtime_path = "C:/missing/voyager-mc-bot"
        bridge = MinecraftBridge(mock_config)

        with patch("os.path.isdir", return_value=False):
            resolved = bridge._resolve_bot_dir()

        assert (
            resolved.endswith("C:\\missing\\voyager-mc-bot")
            or resolved == "C:/missing/voyager-mc-bot"
        )

    def test_resolve_bot_dir_uses_embedded_path_only_when_enabled(self, mock_config):
        mock_config.runtime.runtime_path = ""
        mock_config.runtime.use_embedded_fallback = True
        bridge = MinecraftBridge(mock_config)

        def is_dir(path):
            normalized = str(path).replace("\\", "/")
            return normalized.endswith("/minecraft/bot")

        with patch("os.path.isdir", side_effect=is_dir):
            resolved = bridge._resolve_bot_dir()

        assert resolved.replace("\\", "/").endswith("/minecraft/bot")


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

    @patch("animetta.tools.minecraft.core.bridge.is_service_available", return_value=True)
    async def test_start_successful(self, mock_is_available, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)

        with (
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)),
            patch("asyncio.wait_for", side_effect=_complete_ready_wait),
        ):
            result = await bridge.start()

        assert result is True
        assert bridge.is_running is True
        assert bridge._process is mock_process

    @patch("animetta.tools.minecraft.core.bridge.is_service_available", return_value=True)
    async def test_start_passes_configured_minecraft_version(
        self, mock_is_available, mock_config, mock_process
    ):
        mock_config.bot.version = "1.21"
        create_proc = AsyncMock(return_value=mock_process)
        bridge = MinecraftBridge(mock_config)

        with (
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", new=create_proc),
            patch("asyncio.wait_for", side_effect=_complete_ready_wait),
        ):
            result = await bridge.start()

        assert result is True
        args = create_proc.await_args.args
        assert args[:6] == (
            "node",
            args[1],
            "localhost",
            "25565",
            "TestBot",
            "1.21",
        )

    @patch("animetta.tools.minecraft.core.bridge.is_service_available", return_value=True)
    async def test_start_login_timeout_stops_unready_runtime(
        self, mock_is_available, mock_config, mock_process
    ):
        bridge = MinecraftBridge(mock_config)

        with (
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)),
            patch("asyncio.wait_for", side_effect=_timeout_ready_wait),
        ):
            result = await bridge.start()

        assert result is False
        assert bridge.is_running is False

    async def test_start_exception_returns_false(self, mock_config):
        bridge = MinecraftBridge(mock_config)

        with (
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("spawn failed")),
        ):
            result = await bridge.start()

        assert result is False
        assert bridge.is_running is False

    async def test_legacy_autonomous_flag_does_not_start_competing_loop(
        self, mock_config, mock_process
    ):
        bridge = MinecraftBridge(mock_config, autonomous=True)

        with (
            patch("animetta.tools.minecraft.core.bridge.is_service_available", return_value=True),
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_process)),
            patch("asyncio.wait_for", side_effect=_complete_ready_wait),
        ):
            result = await bridge.start()

        assert result is True


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
        assert decoded["params"] == {"x": 0, "y": 64, "z": 0, "timeout": 60000}

    async def test_send_command_timeout(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await bridge.send_command("goto", timeout=0.1)

        assert result["status"] == "error"
        assert "timed out" in result["result"]

    async def test_send_command_timeout_triggers_restart_for_long_running_actions(
        self, mock_config, mock_process
    ):
        """Timeout of collect/mine_shaft/branch_mine must trigger a bridge restart."""
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        stop_called = False
        start_called = False

        async def fake_stop():
            nonlocal stop_called
            stop_called = True

        async def fake_start():
            nonlocal start_called
            start_called = True
            return True

        bridge.stop = fake_stop
        bridge.start = fake_start

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await bridge.send_command("collect", timeout=0.1)

        assert result["status"] == "error"
        assert stop_called
        assert start_called

    async def test_send_command_timeout_no_restart_for_short_running_actions(
        self, mock_config, mock_process
    ):
        """Timeout of regular actions (not collect/mine_shaft/branch_mine) must NOT restart."""
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        restart_called = False

        async def fake_stop():
            nonlocal restart_called
            restart_called = True

        bridge.stop = fake_stop

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await bridge.send_command("goto", timeout=0.1)

        assert result["status"] == "error"
        assert not restart_called

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
        mock_process.stdout.readline = AsyncMock(
            side_effect=[
                line,
                b"",  # EOF → stops loop
            ]
        )

        await bridge._read_stdout()
        assert future.done()
        assert future.result() == {"status": "success", "result": "done"}

    async def test_read_stdout_handles_invalid_json(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        mock_process.stdout.readline = AsyncMock(
            side_effect=[
                b"not json\n",
                b"",  # EOF
            ]
        )

        # Should not crash on invalid JSON
        await bridge._read_stdout()

    async def test_read_stdout_login_event_sets_ready(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process

        line = (
            json.dumps(
                {"id": None, "status": "event", "result": {"type": "login", "username": "AnimaBot"}}
            ).encode("utf-8")
            + b"\n"
        )

        mock_process.stdout.readline = AsyncMock(side_effect=[line, b""])

        await bridge._read_stdout()
        assert bridge._bot_ready.is_set()

    async def test_read_stdout_forwards_client_viewer_status_event(self, mock_config, mock_process):
        bridge = MinecraftBridge(mock_config)
        bridge._running = True
        bridge._process = mock_process
        events = []
        bridge.set_viewer_callback(lambda event_type, payload: events.append((event_type, payload)))

        payload = {
            "type": "client_viewer_status",
            "state": "waiting",
            "username": "CameraGuy",
            "mode": "spectator",
            "reason": "poll_detected",
        }
        line = (
            json.dumps(
                {
                    "id": None,
                    "status": "event",
                    "result": payload,
                }
            ).encode("utf-8")
            + b"\n"
        )
        mock_process.stdout.readline = AsyncMock(side_effect=[line, b""])

        await bridge._read_stdout()

        assert events == [("client_viewer_status", payload)]

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

        line = (
            json.dumps({"id": 999, "status": "success", "result": "orphan"}).encode("utf-8") + b"\n"
        )
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
            result = await bridge.set_planner_mode(
                [{"action": "goto", "params": {"x": 0, "y": 64, "z": 0}}]
            )

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
