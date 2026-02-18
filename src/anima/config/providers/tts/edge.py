"""Edge TTS 提供者配置"""

from typing import Literal
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register("tts", "edge")
class EdgeTTSConfig(TTSBaseConfig):
    """Edge TTS 配置（微软免费 TTS）"""
    type: Literal["edge"] = "edge"
    voice: str = Field(default="zh-CN-XiaoxiaoNeural", description="声音/音色")