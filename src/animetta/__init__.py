"""
Animetta - Animated Narrative Intelligence & Messaging Assistant
一个富有灵魂的 AI 虚拟伴侣框架

名称来源：
- 意大利语 "animetta" = 小灵魂（anima 的爱称形式）
- 延续拉丁语 "anima" = 灵魂、生命力的精神内核
"""

__version__ = "0.1.0"
__author__ = "Animetta Team"


# Lazy imports to avoid ImportError when dependencies are not installed
# (e.g., during package installation or when running scripts that don't need all modules)
def __getattr__(name: str):
    if name == "AgentConfig":
        from .config import AgentConfig

        return AgentConfig
    if name == "EffectiveConfig":
        from .config import EffectiveConfig

        return EffectiveConfig
    if name == "ASRConfig":
        from .config import ASRConfig

        return ASRConfig
    if name == "LLMConfig":
        from .config import LLMConfig

        return LLMConfig
    if name == "PersonaConfig":
        from .config import PersonaConfig

        return PersonaConfig
    if name == "SystemConfig":
        from .config import SystemConfig

        return SystemConfig
    if name == "TTSConfig":
        from .config import TTSConfig

        return TTSConfig
    if name == "ServiceContext":
        from .runtime.session_context import ServiceContext

        return ServiceContext
    if name == "ASRInterface":
        from .services import ASRInterface

        return ASRInterface
    if name == "LLMInterface":
        from .services import LLMInterface

        return LLMInterface
    if name == "TTSInterface":
        from .services import TTSInterface

        return TTSInterface
    raise AttributeError(f"module 'animetta' has no attribute {name!r}")


__all__ = [
    "EffectiveConfig",
    "ASRConfig",
    "TTSConfig",
    "LLMConfig",
    "AgentConfig",
    "PersonaConfig",
    "SystemConfig",
    "ServiceContext",
    "ASRInterface",
    "TTSInterface",
    "LLMInterface",
]
