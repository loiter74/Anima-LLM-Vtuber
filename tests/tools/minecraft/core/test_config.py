from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.minecraft.core.config import (
    MinecraftConfig,
    MinecraftMcpConfig,
    MinecraftSafetyConfig,
)


def test_mcp_config_has_path_independent_defaults() -> None:
    config = MinecraftMcpConfig()

    assert config.url == "http://127.0.0.1:8768/mcp"
    assert config.cli_command == "mc-mcp"
    assert config.default_profile == "external-local"


def test_mcp_config_accepts_multi_argument_cli_command() -> None:
    config = MinecraftMcpConfig(cli_command=["node", "services/mc-mcp/src/mcp/cli.js"])

    assert config.cli_command == ("node", "services/mc-mcp/src/mcp/cli.js")


def test_mcp_config_rejects_empty_cli_arguments() -> None:
    with pytest.raises(ValidationError, match="non-empty arguments"):
        MinecraftMcpConfig(cli_command=["node", ""])


def test_minecraft_config_keeps_anima_policy_and_persistence() -> None:
    config = MinecraftConfig(enabled=True, safety=MinecraftSafetyConfig(max_distance=300))

    assert config.enabled is True
    assert config.safety.max_distance == 300
    assert config.journal_path == "data/minecraft_commands.db"


@pytest.mark.parametrize("field", ["bot", "viewer", "client_viewer", "runtime"])
def test_runtime_ownership_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="runtime ownership moved to mc-mcp"):
        MinecraftConfig.model_validate({field: {}})


@pytest.mark.parametrize("field", ["mode", "autonomous"])
def test_removed_control_plane_fields_have_explicit_migration_error(field: str) -> None:
    with pytest.raises(ValidationError, match="Removed Minecraft config field"):
        MinecraftConfig.model_validate({field: "learn"})
