"""OpenAI TTS provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "openai")
class OpenAITTSConfig(TTSBaseConfig):
    """OpenAI TTS configuration"""

    type: Literal["openai"] = "openai"
    model: str = Field(default="tts-1", description="TTS model name")
    voice: str = Field(default="alloy", description="Voice / timbre")
