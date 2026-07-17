"""DashScope Qwen realtime TTS provider configuration."""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "dashscope")
class DashScopeTTSConfig(TTSBaseConfig):
    """Direct Beijing-region Qwen3-TTS realtime configuration."""

    type: Literal["dashscope"] = "dashscope"
    model: str = Field(default="qwen3-tts-instruct-flash-realtime", min_length=1)
    voice: str = Field(default="Seren", min_length=1)
    base_url: str = Field(
        default="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        pattern=r"^wss://dashscope\.aliyuncs\.com/api-ws/v1/realtime$",
    )
    response_format: Literal["pcm"] = "pcm"
    sample_rate: Literal[24000] = 24000
    language_type: Literal["Chinese"] = "Chinese"
    timeout_seconds: float = Field(default=20.0, gt=0)
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
