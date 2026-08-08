"""
Minecraft configuration models
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MinecraftBotConfig(BaseModel):
    host: str = "localhost"
    port: int = 25565
    username: str = "AnimaBot"
    version: str | None = None  # None = auto-detect by Mineflayer


class MinecraftSafetyConfig(BaseModel):
    no_griefing: bool = True
    auto_heal: bool = True
    max_distance: int = 500


class MinecraftViewerConfig(BaseModel):
    """Configuration for first-person spectator viewing."""

    username: str = ""  # MC username of the viewer player
    auto_spectate: bool = True  # Auto-spectate when viewer joins


class MinecraftClientViewerConfig(BaseModel):
    """Configuration for real Minecraft client capture mode.

    A separate Minecraft client account acts as a camera/presentation layer
    while Mineflayer remains the action executor. The bot detects the viewer
    account on the server and optionally binds it via /spectate.
    """

    enabled: bool = False
    username: str = "LUN077"  # MC username of the real-client viewer account
    mode: Literal["spectator"] = "spectator"  # binding mode: only "spectator" for now
    auto_spectate: bool = True  # auto-run /spectate when viewer is online
    poll_interval: int = 20  # seconds between viewer-online polling checks
    spectate_timeout: int = 8  # seconds to wait for spectate command result


class MinecraftRuntimeConfig(BaseModel):
    """External runtime configuration for the Minecraft bot process.

    When a runtime_path is configured, the bridge launches the bot from that
    directory. If empty, the bridge defaults to the external voyager-mc-bot
    project directory (assumed sibling of the Anima repo).
    """

    runtime_path: str = ""  # empty → default to voyager-mc-bot sibling
    entrypoint: str = "index.js"  # relative to runtime_path
    package_manager: str = "npm"  # npm | yarn | pnpm
    use_embedded_fallback: bool = False  # embedded runtime has been migrated out
    install_command: str = ""  # empty → derive from package_manager ("npm install")


class MinecraftConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    queue_capacity: int = Field(default=100, gt=0, le=10_000)
    max_tool_wait_seconds: float = Field(default=10, ge=0, le=60)
    cancellation_grace_seconds: float = Field(default=10, gt=0, le=120)
    reconciliation_timeout_seconds: float = Field(default=30, gt=0, le=300)
    journal_path: str = "data/minecraft_commands.db"
    skill_path: str = "data/mc_skills.db"
    bot: MinecraftBotConfig = Field(default_factory=MinecraftBotConfig)
    safety: MinecraftSafetyConfig = Field(default_factory=MinecraftSafetyConfig)
    viewer: MinecraftViewerConfig = Field(default_factory=MinecraftViewerConfig)
    client_viewer: MinecraftClientViewerConfig = Field(default_factory=MinecraftClientViewerConfig)
    runtime: MinecraftRuntimeConfig = Field(default_factory=MinecraftRuntimeConfig)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_viewer(cls, value: object) -> object:
        """Promote legacy viewer settings when canonical settings are absent."""
        if not isinstance(value, dict):
            return value
        removed = sorted({"mode", "autonomous"} & value.keys())
        if removed:
            raise ValueError(
                "Removed Minecraft config field(s): "
                + ", ".join(removed)
                + "; submit a typed mission policy or bounded atomic probe"
            )
        if "client_viewer" in value:
            return value
        legacy = value.get("viewer")
        if not isinstance(legacy, dict):
            return value
        username = legacy.get("username")
        if not isinstance(username, str) or not username.strip():
            return value
        normalized = dict(value)
        normalized["client_viewer"] = {
            "enabled": True,
            "username": username,
            "auto_spectate": bool(legacy.get("auto_spectate", True)),
        }
        return normalized
