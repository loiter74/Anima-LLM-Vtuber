"""Xiaomi MiMo ASR provider configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register_config("asr", "mimo")
class MimoASRConfig(ASRBaseConfig):
    """MiMo V2.5 speech recognition configuration."""

    type: Literal["mimo"] = "mimo"
    model: str = Field(default="mimo-v2.5-asr", description="MiMo ASR model")
    base_url: str = Field(default="https://api.xiaomimimo.com/v1", description="MiMo API base URL")
    language: Literal["auto", "zh", "en"] = Field(
        default="auto", description="Recognition language"
    )
    sample_rate: int = Field(default=16000, ge=8000, description="Raw PCM sample rate")
    input_audio_format: Literal["pcm_s16le", "wav", "mp3"] = Field(
        default="pcm_s16le",
        description="Format to assume when audio_data is bytes",
    )
    timeout: float = Field(default=30.0, gt=0, description="HTTP timeout in seconds")
