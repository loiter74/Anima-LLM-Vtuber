"""Xiaomi MiMo VAD configuration."""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import VADBaseConfig


@ProviderRegistry.register_config("vad", "mimo")
class MimoVADConfig(VADBaseConfig):
    """Hybrid VAD with local endpointing and optional MiMo ASR confirmation."""

    type: Literal["mimo"] = "mimo"
    api_key: str | None = Field(default=None, description="MiMo API key")
    model: str = Field(default="mimo-v2.5-asr", description="MiMo ASR model")
    base_url: str = Field(
        default="https://api.xiaomimimo.com/v1",
        description="MiMo OpenAI-compatible API base URL",
    )
    language: Literal["auto", "zh", "en"] = Field(
        default="auto",
        description="ASR language hint",
    )
    audio_format: Literal["wav"] = Field(
        default="wav",
        description="Audio format sent to MiMo ASR",
    )
    db_threshold: float = Field(default=-35.0, description="Local speech dB threshold")
    min_speech_duration: int = Field(
        default=2,
        ge=1,
        description="Consecutive loud frames required to start speech",
    )
    min_silence_duration: int = Field(
        default=8,
        ge=1,
        description="Consecutive silent frames required to end speech",
    )
    confirm_with_asr: bool = Field(
        default=True,
        description="Confirm completed speech segments with MiMo ASR",
    )
    timeout: float = Field(default=15.0, gt=0, description="HTTP timeout in seconds")
