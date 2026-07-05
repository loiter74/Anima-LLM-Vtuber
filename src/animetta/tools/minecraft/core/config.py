"""
Minecraft configuration models
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


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
    username: str = ""  # MC username of the real-client viewer account
    mode: Literal["spectator"] = "spectator"  # binding mode: only "spectator" for now
    auto_spectate: bool = True  # auto-run /spectate when viewer is online
    poll_interval: int = 30  # seconds between viewer-online polling checks
    spectate_timeout: int = 10  # seconds to wait for spectate command result


class MinecraftMode(StrEnum):
    """Bot 运行模式（mc-bot-voyager-learning）。

    FALLBACK: 纯 Survival Runner 确定性流程（默认，最可靠）
    LEARN:    Voyager 学习期——自动课程 + 迭代代码生成 + 自我验证闭环，攒 verified 技能
    LIVE:     直播期——从 verified 技能库选技能执行，不生成新代码
    """

    FALLBACK = "fallback"
    LEARN = "learn"
    LIVE = "live"


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
    enabled: bool = False
    mode: MinecraftMode = MinecraftMode.FALLBACK
    autonomous: bool = False  # deprecated: 由 mode != FALLBACK 派生；保留向后兼容
    bot: MinecraftBotConfig = MinecraftBotConfig()
    safety: MinecraftSafetyConfig = MinecraftSafetyConfig()
    viewer: MinecraftViewerConfig = MinecraftViewerConfig()
    client_viewer: MinecraftClientViewerConfig = MinecraftClientViewerConfig()
    runtime: MinecraftRuntimeConfig = MinecraftRuntimeConfig()
