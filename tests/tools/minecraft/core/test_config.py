from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from animetta.tools.minecraft.core.config import (
    MinecraftConfig,
    MinecraftMcpConfig,
    MinecraftPresentationConfig,
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


def test_presentation_defaults_off_and_has_bounded_replay_retention() -> None:
    presentation = MinecraftConfig().presentation

    assert presentation == MinecraftPresentationConfig(
        mode="off",
        tempo="normal",
        seed="animetta-live-v1",
        replay_limit=64,
        retention_seconds=86_400,
    )


def test_bundled_presentation_stays_off_until_formal_acceptance() -> None:
    project_root = Path(__file__).resolve().parents[4]
    tools = yaml.safe_load((project_root / "config" / "tools.yaml").read_text(encoding="utf-8"))

    assert tools["minecraft"]["presentation"]["mode"] == "off"


def test_presentation_accepts_the_canonical_public_policy() -> None:
    config = MinecraftConfig.model_validate(
        {
            "presentation": {
                "mode": "full",
                "tempo": "brisk",
                "seed": "livestream-seed:v2",
                "replay_limit": 12,
                "retention_seconds": 600,
            }
        }
    )

    assert config.presentation.mode == "full"
    assert config.presentation.tempo == "brisk"
    assert config.presentation.seed == "livestream-seed:v2"
    assert config.presentation.replay_limit == 12
    assert config.presentation.retention_seconds == 600


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "enabled"),
        ("tempo", "instant"),
        ("seed", 42),
        ("seed", ""),
        ("seed", "contains spaces"),
        ("replay_limit", 0),
        ("retention_seconds", 59),
    ],
)
def test_presentation_rejects_noncanonical_or_unbounded_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        MinecraftPresentationConfig.model_validate({field: value})


def test_presentation_rejects_a_second_enabled_switch() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MinecraftPresentationConfig.model_validate({"enabled": True})


def test_presentation_force_off_is_one_way(monkeypatch) -> None:
    enabled = MinecraftPresentationConfig(mode="full")
    disabled = MinecraftPresentationConfig(mode="off")

    monkeypatch.setenv("MC_MCP_PRESENTATION_FORCE_OFF", "true")
    assert enabled.effective_mode == "off"
    monkeypatch.setenv("MC_MCP_PRESENTATION_FORCE_OFF", "false")
    assert enabled.effective_mode == "full"
    assert disabled.effective_mode == "off"


@pytest.mark.parametrize("field", ["bot", "viewer", "client_viewer", "runtime"])
def test_runtime_ownership_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="runtime ownership moved to mc-mcp"):
        MinecraftConfig.model_validate({field: {}})


@pytest.mark.parametrize("field", ["mode", "autonomous"])
def test_removed_control_plane_fields_have_explicit_migration_error(field: str) -> None:
    with pytest.raises(ValidationError, match="Removed Minecraft config field"):
        MinecraftConfig.model_validate({field: "learn"})
