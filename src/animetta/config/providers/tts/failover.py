"""Composite cloud-to-local TTS provider configuration."""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig
from .dashscope import DashScopeTTSConfig
from .remote import RemoteTTSConfig


@ProviderRegistry.register_config("tts", "failover")
class FailoverTTSConfig(TTSBaseConfig):
    """Exact DashScope primary and authenticated remote fallback pair."""

    type: Literal["failover"] = "failover"
    model: str = "failover"
    voice: str = "dynamic"
    primary: DashScopeTTSConfig
    fallback: RemoteTTSConfig
    cooldown_seconds: float = Field(default=300.0, gt=0)
    primary_pre_audio_retries: Literal[1] = 1
