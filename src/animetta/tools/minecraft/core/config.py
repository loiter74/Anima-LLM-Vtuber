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


class MinecraftWebViewerConfig(BaseModel):
    """Configuration for optional first-person web viewing."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 3007


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


class MinecraftConfig(BaseModel):
    enabled: bool = False
    mode: MinecraftMode = MinecraftMode.FALLBACK
    autonomous: bool = False  # deprecated: 由 mode != FALLBACK 派生；保留向后兼容
    bot: MinecraftBotConfig = MinecraftBotConfig()
    safety: MinecraftSafetyConfig = MinecraftSafetyConfig()
    viewer: MinecraftViewerConfig = MinecraftViewerConfig()
    web_viewer: MinecraftWebViewerConfig = MinecraftWebViewerConfig()
    client_viewer: MinecraftClientViewerConfig = MinecraftClientViewerConfig()
