"""
Anima - Animated Narrative Intelligence & Messaging Assistant
一个富有灵魂的 AI 虚拟伴侣框架

名称来源：
- 拉丁语 "anima" = 灵魂、生命力
- 荣格心理学中的 "阿尼玛" = 内在的女性原型
"""

__version__ = "0.1.0"
__author__ = "Anima Team"

from .config import (
    AppConfig,
    ASRConfig,
    TTSConfig,
    LLMConfig,
    AgentConfig,
    PersonaConfig,
    SystemConfig,
)
from .service_context import ServiceContext
from .services import ASRInterface, TTSInterface, AgentInterface

__all__ = [
    "AppConfig",
    "ASRConfig",
    "TTSConfig",
    "LLMConfig",
    "AgentConfig",
    "PersonaConfig",
    "SystemConfig",
    "ServiceContext",
    "ASRInterface",
    "TTSInterface",
    "AgentInterface",
]
