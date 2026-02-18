"""提供者配置模块"""

from .llm import LLMConfig, LLMBaseConfig
from .asr import ASRConfig, ASRBaseConfig
from .tts import TTSConfig, TTSBaseConfig

__all__ = [
    # LLM
    "LLMConfig",
    "LLMBaseConfig",
    # ASR
    "ASRConfig",
    "ASRBaseConfig",
    # TTS
    "TTSConfig",
    "TTSBaseConfig",
]