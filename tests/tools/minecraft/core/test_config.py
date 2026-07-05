from __future__ import annotations

from animetta.tools.minecraft.core.config import (
    MinecraftBotConfig,
    MinecraftConfig,
    MinecraftMode,
    MinecraftRuntimeConfig,
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


class TestMinecraftRuntimeConfig:
    """MinecraftRuntimeConfig model tests."""

    def test_default_values(self):
        cfg = MinecraftRuntimeConfig()
        assert cfg.runtime_path == ""
        assert cfg.entrypoint == "index.js"
        assert cfg.package_manager == "npm"
        assert cfg.use_embedded_fallback is False
        assert cfg.install_command == ""

    def test_external_runtime_full_config(self):
        cfg = MinecraftRuntimeConfig(
            runtime_path="C:/Users/30262/Project/voyager-mc-bot",
            entrypoint="src/index.js",
            package_manager="pnpm",
            use_embedded_fallback=True,
            install_command="pnpm install --frozen-lockfile",
        )
        assert cfg.runtime_path == "C:/Users/30262/Project/voyager-mc-bot"
        assert cfg.entrypoint == "src/index.js"
        assert cfg.package_manager == "pnpm"
        assert cfg.use_embedded_fallback is True

    def test_default_in_minecraft_config(self):
        cfg = MinecraftConfig()
        assert cfg.runtime.runtime_path == ""
        assert cfg.runtime.entrypoint == "index.js"


class TestMinecraftConfig:
    """MinecraftConfig model tests."""

    def test_default_values(self):
        cfg = MinecraftConfig()
        assert cfg.enabled is False
        assert cfg.mode == MinecraftMode.FALLBACK
        assert cfg.bot.host == "localhost"
        assert cfg.bot.port == 25565
        assert cfg.safety.no_griefing is True

    def test_enabled_config(self):
        cfg = MinecraftConfig(
            enabled=True,
            mode=MinecraftMode.LEARN,
            bot=MinecraftBotConfig(host="mc.example.com", username="TestBot"),
        )
        assert cfg.enabled is True
        assert cfg.mode == MinecraftMode.LEARN
        assert cfg.bot.host == "mc.example.com"
        assert cfg.bot.username == "TestBot"

    def test_nested_safety_config(self):
        cfg = MinecraftConfig(
            safety=MinecraftSafetyConfig(max_distance=300)
        )
        assert cfg.safety.max_distance == 300
