"""Tests for Minecraft spectator viewer feature."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.tools.minecraft.core.config import (
    MinecraftConfig,
    MinecraftViewerConfig,
)


class TestMinecraftViewerConfig:
    """Test MinecraftViewerConfig model parsing."""

    def test_default_values(self):
        cfg = MinecraftViewerConfig()
        assert cfg.username == ""
        assert cfg.auto_spectate is True

    def test_custom_values(self):
        cfg = MinecraftViewerConfig(username="Cowork", auto_spectate=False)
        assert cfg.username == "Cowork"
        assert cfg.auto_spectate is False

    def test_viewer_in_minecraft_config(self):
        cfg = MinecraftConfig(
            enabled=True,
            viewer=MinecraftViewerConfig(username="TestPlayer"),
        )
        assert cfg.viewer.username == "TestPlayer"
        assert cfg.viewer.auto_spectate is True

    def test_viewer_default_empty(self):
        cfg = MinecraftConfig(enabled=True)
        assert cfg.viewer.username == ""
        assert cfg.viewer.auto_spectate is True

    def test_parse_from_dict(self):
        data = {
            "enabled": True,
            "viewer": {"username": "Cowork", "auto_spectate": False},
        }
        cfg = MinecraftConfig(**data)
        assert cfg.viewer.username == "Cowork"
        assert cfg.viewer.auto_spectate is False


class TestBridgeViewerMethods:
    """Test MinecraftBridge viewer-related methods."""

    @pytest.fixture
    def bridge(self):
        from animetta.tools.minecraft.core.bridge import MinecraftBridge

        config = MinecraftConfig(
            enabled=True,
            viewer=MinecraftViewerConfig(username="Cowork"),
        )
        return MinecraftBridge(config)

    def test_viewer_callback_default_none(self, bridge):
        assert bridge._viewer_callback is None

    def test_set_viewer_callback(self, bridge):
        callback = MagicMock()
        bridge.set_viewer_callback(callback)
        assert bridge._viewer_callback is callback

    @pytest.mark.asyncio
    async def test_spectate_viewer_not_running(self, bridge):
        result = await bridge.spectate_viewer()
        assert result["status"] == "error"
        assert "not running" in result["result"].lower()

    @pytest.mark.asyncio
    async def test_spectate_viewer_with_username(self, bridge):
        # Mock the send_command to capture what gets sent
        bridge._running = True
        bridge._process = MagicMock()
        bridge._process.returncode = None
        bridge._process.stdin = MagicMock()
        bridge._process.stdin.write = MagicMock()
        bridge._process.stdin.drain = AsyncMock()

        # Patch send_command to return success
        with patch.object(bridge, "send_command", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"status": "success", "result": "Spectating: Cowork"}
            result = await bridge.spectate_viewer("Cowork")
            mock_send.assert_called_once_with("spectate", {"username": "Cowork"}, timeout=10.0)
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_spectate_viewer_no_username(self, bridge):
        with patch.object(bridge, "send_command", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"status": "success", "result": "Spectating: Cowork"}
            await bridge.spectate_viewer()
            mock_send.assert_called_once_with("spectate", {}, timeout=10.0)

    def test_viewer_callback_invoked_on_event(self, bridge):
        callback = MagicMock()
        bridge.set_viewer_callback(callback)

        # Simulate the callback being called (as _read_stdout would)
        bridge._viewer_callback("viewer_joined", "Cowork")
        callback.assert_called_once_with("viewer_joined", "Cowork")
