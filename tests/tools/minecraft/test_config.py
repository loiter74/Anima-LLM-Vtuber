from __future__ import annotations

from animetta.tools.minecraft.config import (
    MinecraftBotConfig,
    MinecraftConfig,
    MinecraftSafetyConfig,
)

"""Tests for Minecraft configuration models."""

import pytest
from pydantic import ValidationError


class TestMinecraftBotConfig:
    """MinecraftBotConfig model tests."""

    def test_default_values(self):
        cfg = MinecraftBotConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 25565
        assert cfg.username == "AnimaBot"
        assert cfg.version is None

    def test_custom_values(self):
        cfg = MinecraftBotConfig(
            host="mc.example.com",
            port=12345,
            username="TestBot",
            version="1.20.4",
        )
        assert cfg.host == "mc.example.com"
        assert cfg.port == 12345
        assert cfg.username == "TestBot"
        assert cfg.version == "1.20.4"

    def test_port_must_be_int(self):
        with pytest.raises(ValidationError):
            MinecraftBotConfig(port="not_a_number")


class TestMinecraftSafetyConfig:
    """MinecraftSafetyConfig model tests."""

    def test_default_values(self):
        cfg = MinecraftSafetyConfig()
        assert cfg.no_griefing is True
        assert cfg.auto_heal is True
        assert cfg.max_distance == 500

    def test_custom_values(self):
        cfg = MinecraftSafetyConfig(
            no_griefing=False,
            auto_heal=False,
            max_distance=1000,
        )
        assert cfg.no_griefing is False
        assert cfg.auto_heal is False
        assert cfg.max_distance == 1000


class TestMinecraftConfig:
    """MinecraftConfig model tests."""

    def test_default_values(self):
        cfg = MinecraftConfig()
        assert cfg.enabled is False
        assert cfg.autonomous is False
        assert cfg.bot.host == "localhost"
        assert cfg.bot.port == 25565
        assert cfg.safety.no_griefing is True

    def test_enabled_config(self):
        cfg = MinecraftConfig(
            enabled=True,
            autonomous=True,
            bot=MinecraftBotConfig(host="mc.example.com", username="TestBot"),
        )
        assert cfg.enabled is True
        assert cfg.autonomous is True
        assert cfg.bot.host == "mc.example.com"
        assert cfg.bot.username == "TestBot"

    def test_nested_safety_config(self):
        cfg = MinecraftConfig(
            safety=MinecraftSafetyConfig(max_distance=300)
        )
        assert cfg.safety.max_distance == 300
