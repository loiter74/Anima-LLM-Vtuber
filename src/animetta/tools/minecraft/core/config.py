"""
Minecraft configuration models
"""


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


class MinecraftConfig(BaseModel):
    enabled: bool = False
    autonomous: bool = False   # Enable autonomous behavior loop
    bot: MinecraftBotConfig = MinecraftBotConfig()
    safety: MinecraftSafetyConfig = MinecraftSafetyConfig()
