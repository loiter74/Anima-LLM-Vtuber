"""Tests for MinecraftClientViewerConfig — real-client capture mode."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.minecraft.core.config import (
    MinecraftClientViewerConfig,
    MinecraftConfig,
)


class TestMinecraftClientViewerConfig:
    """MinecraftClientViewerConfig model tests."""

    def test_default_values(self):
        cfg = MinecraftClientViewerConfig()
        assert cfg.enabled is False
        assert cfg.username == ""
        assert cfg.mode == "spectator"
        assert cfg.auto_spectate is True
        assert cfg.poll_interval == 30
        assert cfg.spectate_timeout == 10

    def test_custom_values(self):
        cfg = MinecraftClientViewerConfig(
            enabled=True,
            username="CoworkCamera",
            mode="spectator",
            auto_spectate=False,
            poll_interval=60,
            spectate_timeout=15,
        )
        assert cfg.enabled is True
        assert cfg.username == "CoworkCamera"
        assert cfg.mode == "spectator"
        assert cfg.auto_spectate is False
        assert cfg.poll_interval == 60
        assert cfg.spectate_timeout == 15

    def test_enabled_without_username_still_valid(self):
        """Config can be enabled without a username — runtime will report missing."""
        cfg = MinecraftClientViewerConfig(enabled=True)
        assert cfg.enabled is True
        assert cfg.username == ""

    def test_mode_must_be_known_value(self):
        with pytest.raises(ValidationError):
            MinecraftClientViewerConfig(mode="invalid_mode")


class TestMinecraftConfigClientViewer:
    """Test client_viewer field on MinecraftConfig."""

    def test_default_client_viewer_disabled(self):
        cfg = MinecraftConfig()
        assert cfg.client_viewer.enabled is False
        assert cfg.client_viewer.username == ""
        assert cfg.client_viewer.mode == "spectator"

    def test_client_viewer_enabled_via_config(self):
        cfg = MinecraftConfig(
            enabled=True,
            client_viewer=MinecraftClientViewerConfig(
                enabled=True,
                username="CameraGuy",
            ),
        )
        assert cfg.client_viewer.enabled is True
        assert cfg.client_viewer.username == "CameraGuy"

    def test_client_viewer_parse_from_dict(self):
        data = {
            "enabled": True,
            "client_viewer": {
                "enabled": True,
                "username": "StreamerCam",
                "auto_spectate": False,
                "poll_interval": 45,
            },
        }
        cfg = MinecraftConfig(**data)
        assert cfg.client_viewer.enabled is True
        assert cfg.client_viewer.username == "StreamerCam"
        assert cfg.client_viewer.auto_spectate is False
        assert cfg.client_viewer.poll_interval == 45

    def test_client_viewer_independent_of_viewer(self):
        """client_viewer and viewer are separate config sections."""
        cfg = MinecraftConfig(
            enabled=True,
            client_viewer=MinecraftClientViewerConfig(enabled=True, username="Camera"),
        )
        assert cfg.client_viewer.enabled is True
        assert cfg.viewer.username == ""  # unchanged

    def test_client_viewer_mode_default_spectator(self):
        cfg = MinecraftConfig(
            client_viewer=MinecraftClientViewerConfig(enabled=True, username="Cam"),
        )
        assert cfg.client_viewer.mode == "spectator"
