"""OpenAI TTS 提供者配置"""

from typing import Optional, Literal
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register("tts", "openai")
class OpenAITTSConfig(TTSBaseConfig):
    """OpenAI TTS 配置"""
    type: Literal["openai"] = "openai"
    model: str = Field(default="tts-1", description="TTS 模型名称")
    voice: str = Field(default="alloy", description="声音/音色")
    base_url: Optional[str] = Field(default=None, description="API Base URL")