"""
Minecraft Gameplay Integration

Provides:
- MinecraftMcpBridge for connecting to the independently managed mc-mcp service
- LangChain @tool decorators for LLM-driven gameplay
- Config models for Minecraft server and safety settings
"""

# Lazy imports to avoid circular/broken import chains
# Import directly from submodules when needed:
#   from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge
#   from animetta.tools.minecraft.core.config import MinecraftConfig
#   from animetta.tools.minecraft.core.tools import mc_connection, mc_operate_bot

from .core.bridge import get_bridge

__all__ = ["get_bridge"]
