"""Edge TTS provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "edge")
class EdgeTTSConfig(TTSBaseConfig):
    """Edge TTS configuration (Microsoft free TTS)"""

    type: Literal["edge"] = "edge"
    voice: str = Field(
        default="zh-CN-XiaoxiaoNeural", description="Voice name, e.g. zh-CN-XiaoxiaoNeural"
    )
    rate: str | None = Field(
        default=None, description="Speech rate adjustment, e.g. '+15%', '-10%'"
    )
    pitch: str | None = Field(
        default=None, description="Voice pitch adjustment, e.g. '+60Hz', '+30%'"
    )
    preset: str | None = Field(
        default=None, description="Voice preset: 'neurosama' for electronic cute voice"
    )
