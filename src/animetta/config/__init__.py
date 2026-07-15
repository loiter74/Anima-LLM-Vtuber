"""
Configuration module (refactored)
Uses plugin-based Provider architecture + Pydantic Discriminated Unions

Architecture:
- core/: Core infrastructure (BaseConfig, ProviderRegistry, Mixins)
- providers/: Provider configurations (LLM/ASR/TTS/VAD/VC/Separation/Bilibili)
- agent.py: Agent configuration (combined LLM)
- persona.py: Persona configuration (includes avatar, etc.)
- system.py: System configuration
- manifest.py: Canonical runtime manifest and immutable effective configuration
"""

# Core
# Composite configs
from .agent import AgentConfig
from .core.base import BaseConfig
from .core.mixins import ApiKeyMixin, DeviceMixin, ModelMixin, TemperatureMixin
from .core.registry import ProviderRegistry
from .humor import HumorConfig
from .manifest import EffectiveConfig, load_effective_config
from .persona import (
    BehaviorRules,
    MBTIDimensionDelta,
    MBTIDimensions,
    MBTIProfile,
    PersonaConfig,
    PersonalityTraits,
)

# Providers - ASR
from .providers.asr import (
    ASRBaseConfig,
    ASRConfig,
    FasterWhisperASRConfig,
    FunASRConfig,
    GLMASRConfig,
    MimoASRConfig,
    MockASRConfig,
    OpenAIASRConfig,
)

# Providers - Bilibili
from .providers.bilibili import BilibiliConfig, ReplyPolicyConfig

# Providers - LLM
from .providers.llm import (
    DeepSeekLLMConfig,
    GLMLLMConfig,
    LLMBaseConfig,
    LLMConfig,
    LocalLoraLLMConfig,
    MockLLMConfig,
    OllamaLLMConfig,
    OpenAILLMConfig,
)

# Providers - Separation
from .providers.separation import (
    DemucsSeparationConfig,
    MockSeparationConfig,
    SeparationBaseConfig,
    SeparationConfig,
)

# Providers - TTS
from .providers.tts import (
    ChatTTSConfig,
    EdgeTTSConfig,
    GLMTTSConfig,
    GPTSoVITSConfig,
    KokoroTTSConfig,
    MockTTSConfig,
    OpenAITTSConfig,
    Qwen3TTSConfig,
    RemoteTTSConfig,
    TTSBaseConfig,
    TTSConfig,
    VibeVoiceTTSConfig,
)

# Providers - VAD
from .providers.vad import (
    MockVADConfig,
    SileroVADConfig,
    VADBaseConfig,
    VADConfig,
)

# Providers - VC
from .providers.vc import (
    MockVCConfig,
    RVCConfig,
    VCBaseConfig,
    VCConfig,
)
from .system import SystemConfig

__all__ = [
    # Core
    "BaseConfig",
    "ProviderRegistry",
    "ApiKeyMixin",
    "ModelMixin",
    "DeviceMixin",
    "TemperatureMixin",
    "HumorConfig",
    # LLM Providers
    "LLMConfig",
    "LLMBaseConfig",
    "MockLLMConfig",
    "OpenAILLMConfig",
    "GLMLLMConfig",
    "OllamaLLMConfig",
    "DeepSeekLLMConfig",
    "LocalLoraLLMConfig",
    # ASR Providers
    "ASRConfig",
    "ASRBaseConfig",
    "MockASRConfig",
    "OpenAIASRConfig",
    "GLMASRConfig",
    "MimoASRConfig",
    "FasterWhisperASRConfig",
    "FunASRConfig",
    # TTS Providers
    "TTSConfig",
    "TTSBaseConfig",
    "MockTTSConfig",
    "OpenAITTSConfig",
    "EdgeTTSConfig",
    "GLMTTSConfig",
    "ChatTTSConfig",
    "VibeVoiceTTSConfig",
    "KokoroTTSConfig",
    "GPTSoVITSConfig",
    "Qwen3TTSConfig",
    "RemoteTTSConfig",
    # VAD Providers
    "VADConfig",
    "VADBaseConfig",
    "MockVADConfig",
    "SileroVADConfig",
    # VC Providers
    "VCConfig",
    "VCBaseConfig",
    "MockVCConfig",
    "RVCConfig",
    # Separation Providers
    "SeparationConfig",
    "SeparationBaseConfig",
    "MockSeparationConfig",
    "DemucsSeparationConfig",
    # Bilibili
    "BilibiliConfig",
    "ReplyPolicyConfig",
    # Composite
    "AgentConfig",
    "SystemConfig",
    # Persona
    "PersonaConfig",
    "PersonalityTraits",
    "BehaviorRules",
    "MBTIDimensions",
    "MBTIDimensionDelta",
    "MBTIProfile",
    # App
    "EffectiveConfig",
    "load_effective_config",
]
