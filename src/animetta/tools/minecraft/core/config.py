"""
Minecraft configuration models
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MinecraftSafetyConfig(BaseModel):
    no_griefing: bool = True
    auto_heal: bool = True
    max_distance: int = 500


class MinecraftMcpConfig(BaseModel):
    """Connection to the independently installed mc-mcp service."""

    url: str = "http://127.0.0.1:8768/mcp"
    cli_command: str = "mc-mcp"
    default_profile: str = "managed-local"
    startup_timeout_seconds: float = Field(default=10, gt=0, le=120)
    request_timeout_seconds: float = Field(default=60, gt=0, le=60)
    event_poll_seconds: float = Field(default=0.5, gt=0, le=10)
    auth_token_env: str = "MC_MCP_AUTH_TOKEN"


class MinecraftConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    queue_capacity: int = Field(default=100, gt=0, le=10_000)
    max_tool_wait_seconds: float = Field(default=10, ge=0, le=60)
    cancellation_grace_seconds: float = Field(default=10, gt=0, le=120)
    reconciliation_timeout_seconds: float = Field(default=30, gt=0, le=300)
    journal_path: str = "data/minecraft_commands.db"
    skill_path: str = "data/mc_skills.db"
    safety: MinecraftSafetyConfig = Field(default_factory=MinecraftSafetyConfig)
    mcp: MinecraftMcpConfig = Field(default_factory=MinecraftMcpConfig)

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
        removed_runtime = sorted({"bot", "viewer", "client_viewer", "runtime"} & value.keys())
        if removed_runtime:
            raise ValueError(
                "Minecraft runtime ownership moved to mc-mcp; remove field(s): "
                + ", ".join(removed_runtime)
            )
        return value
