"""
Minecraft configuration models
"""


from enum import Enum

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
    username: str = ""          # MC username of the viewer player
    auto_spectate: bool = True  # Auto-spectate when viewer joins


class MinecraftMode(str, Enum):
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
