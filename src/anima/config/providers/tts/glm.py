"""智谱 AI GLM TTS 提供者配置"""

from typing import Literal
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register("tts", "glm")
class GLMTTSConfig(TTSBaseConfig):
    """智谱 AI GLM TTS 配置"""
    type: Literal["glm"] = "glm"
    model: str = Field(default="glm-tts", description="TTS 模型名称")
    voice: str = Field(default="default", description="声音/音色")
    response_format: str = Field(default="wav", description="音频格式: wav/mp3")
    volume: float = Field(default=1.0, description="音量: 0.0-2.0")
