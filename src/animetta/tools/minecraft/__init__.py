"""
Minecraft Gameplay Integration

Provides:
- MinecraftBridge for managing Mineflayer bot subprocess lifecycle
- LangChain @tool decorators for LLM-driven gameplay
- Config models for Minecraft server and safety settings
"""

# Lazy imports to avoid circular/broken import chains
# Import directly from submodules when needed:
#   from animetta.tools.minecraft.core.bridge import MinecraftBridge
#   from animetta.tools.minecraft.core.config import MinecraftConfig
#   from animetta.tools.minecraft.survival.runner import SurvivalIronRunner

from .core.bridge import get_bridge

__all__ = ["get_bridge"]
