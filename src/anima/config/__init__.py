"""
配置模块（重构版）
使用插件化 Provider 架构 + Pydantic Discriminated Unions

架构:
- core/: 核心基础设施（BaseConfig, ProviderRegistry）
- providers/: 提供者配置（LLM/ASR/TTS 各类实现）
- agent.py: Agent 配置（组合 LLM）
- persona.py: 人设配置（含头像等）
- system.py: 系统配置
- app.py: 应用总配置
"""

# Core
from .core.base import BaseConfig
from .core.registry import ProviderRegistry

# Providers - LLM
from .providers.llm import (
    LLMConfig,
    LLMBaseConfig,
    MockLLMConfig,
    OpenAILLMConfig,
    GLMLLMConfig,
    OllamaLLMConfig,
)

# Providers - ASR
from .providers.asr import (
    ASRConfig,
    ASRBaseConfig,
    MockASRConfig,
    OpenAIASRConfig,
    GLMASRConfig,
)

# Providers - TTS
from .providers.tts import (
    TTSConfig,
    TTSBaseConfig,
    MockTTSConfig,
    OpenAITTSConfig,
    EdgeTTSConfig,
    GLMTTSConfig,
)

# Composite configs
from .agent import AgentConfig
from .system import SystemConfig
from .persona import PersonaConfig, PersonalityTraits, BehaviorRules
from .app import AppConfig

__all__ = [
    # Core
    "BaseConfig",
    "ProviderRegistry",
    # LLM Providers
    "LLMConfig",
    "LLMBaseConfig",
    "MockLLMConfig",
    "OpenAILLMConfig",
    "GLMLLMConfig",
    "OllamaLLMConfig",
    # ASR Providers
    "ASRConfig",
    "ASRBaseConfig",
    "MockASRConfig",
    "OpenAIASRConfig",
    "GLMASRConfig",
    # TTS Providers
    "TTSConfig",
    "TTSBaseConfig",
    "MockTTSConfig",
    "OpenAITTSConfig",
    "EdgeTTSConfig",
    "GLMTTSConfig",
    # Composite
    "AgentConfig",
    "SystemConfig",
    # Persona
    "PersonaConfig",
    "PersonalityTraits",
    "BehaviorRules",
    # App
    "AppConfig",
]