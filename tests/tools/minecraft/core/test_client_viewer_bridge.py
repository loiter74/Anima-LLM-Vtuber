"""Tests for client-viewer environment export in MinecraftBridge.start()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from animetta.tools.minecraft.core.bridge import MinecraftBridge
from animetta.tools.minecraft.core.config import (
    MinecraftBotConfig,
    MinecraftClientViewerConfig,
    MinecraftConfig,
)


async def _complete_ready_wait(awaitable, timeout):
    awaitable.close()
    return None


class TestBridgeClientViewerEnvExport:
    """Verify bridge.start() passes client_viewer settings to Node environment."""

    @patch("animetta.tools.minecraft.core.bridge.is_service_available", return_value=True)
    async def test_client_viewer_enabled_exports_env(self, mock_is_available, tmp_path):
        """When client_viewer.enabled=True, bridge exports MC_CLIENT_VIEWER_* vars."""
        cfg = MinecraftConfig(
            enabled=True,
            bot=MinecraftBotConfig(host="localhost", port=25565, username="TestBot"),
            client_viewer=MinecraftClientViewerConfig(
                enabled=True,
                username="CameraGuy",
                mode="spectator",
                auto_spectate=True,
                poll_interval=45,
                spectate_timeout=12,
            ),
        )
        bridge = MinecraftBridge(cfg)

        captured_env = {}

        async def fake_create(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            proc = MagicMock()
            proc.pid = 1
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

        with (
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", side_effect=fake_create),
            patch("asyncio.wait_for", side_effect=_complete_ready_wait),
        ):
            await bridge.start()

        assert captured_env.get("MC_CLIENT_VIEWER_ENABLED") == "true"
        assert captured_env.get("MC_CLIENT_VIEWER_USERNAME") == "CameraGuy"
        assert captured_env.get("MC_CLIENT_VIEWER_MODE") == "spectator"
        assert captured_env.get("MC_CLIENT_VIEWER_AUTO_SPECTATE") == "true"
        assert captured_env.get("MC_CLIENT_VIEWER_POLL_INTERVAL") == "45"
        assert captured_env.get("MC_CLIENT_VIEWER_SPECTATE_TIMEOUT") == "12"

    @patch("animetta.tools.minecraft.core.bridge.is_service_available", return_value=True)
    async def test_legacy_viewer_exports_single_canonical_controller_config(
        self, mock_is_available
    ):
        cfg = MinecraftConfig(
            enabled=True,
            viewer={"username": "LUN077", "auto_spectate": True},
        )
        bridge = MinecraftBridge(cfg)
        captured_env = {}

        async def fake_create(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            proc = MagicMock(
                pid=1,
                returncode=None,
                stdin=MagicMock(write=MagicMock(), drain=AsyncMock()),
                stdout=MagicMock(readline=AsyncMock(return_value=b"")),
                stderr=MagicMock(readline=AsyncMock(return_value=b"")),
                terminate=MagicMock(),
                kill=MagicMock(),
                wait=AsyncMock(),
            )
            return proc

        with (
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", side_effect=fake_create),
            patch("asyncio.wait_for", side_effect=_complete_ready_wait),
        ):
            await bridge.start()

        assert captured_env["MC_VIEWER_USERNAME"] == "LUN077"
        assert captured_env["MC_CLIENT_VIEWER_ENABLED"] == "true"
        assert captured_env["MC_CLIENT_VIEWER_USERNAME"] == "LUN077"
        assert captured_env["MC_CLIENT_VIEWER_POLL_INTERVAL"] == "20"
        assert captured_env["MC_CLIENT_VIEWER_SPECTATE_TIMEOUT"] == "8"

    @patch("animetta.tools.minecraft.core.bridge.is_service_available", return_value=True)
    async def test_client_viewer_disabled_no_env_vars(self, mock_is_available):
        """When client_viewer.enabled=False, no MC_CLIENT_VIEWER_* vars are set."""
        cfg = MinecraftConfig(
            enabled=True,
            client_viewer=MinecraftClientViewerConfig(enabled=False),
        )
        bridge = MinecraftBridge(cfg)

        captured_env = {}

        async def fake_create(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            proc = MagicMock()
            proc.pid = 1
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

        with (
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", side_effect=fake_create),
            patch("asyncio.wait_for", side_effect=_complete_ready_wait),
        ):
            await bridge.start()

        # No MC_CLIENT_VIEWER_* keys should be present
        assert "MC_CLIENT_VIEWER_ENABLED" not in captured_env
        assert "MC_CLIENT_VIEWER_USERNAME" not in captured_env

    @patch("animetta.tools.minecraft.core.bridge.is_service_available", return_value=True)
    async def test_client_viewer_enabled_without_username_exports_empty(self, mock_is_available):
        """When enabled but username empty, still exports enabled=true with empty username."""
        cfg = MinecraftConfig(
            enabled=True,
            client_viewer=MinecraftClientViewerConfig(enabled=True, username=""),
        )
        bridge = MinecraftBridge(cfg)

        captured_env = {}

        async def fake_create(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            proc = MagicMock()
            proc.pid = 1
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

        with (
            patch("os.path.exists", return_value=True),
            patch("asyncio.create_subprocess_exec", side_effect=fake_create),
            patch("asyncio.wait_for", side_effect=_complete_ready_wait),
        ):
            await bridge.start()

        assert captured_env.get("MC_CLIENT_VIEWER_ENABLED") == "true"
        assert captured_env.get("MC_CLIENT_VIEWER_USERNAME") == ""
