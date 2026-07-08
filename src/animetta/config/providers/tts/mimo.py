"""Xiaomi MiMo TTS provider configuration."""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "mimo")
class MimoTTSConfig(TTSBaseConfig):
    """Xiaomi MiMo speech synthesis V2.5 configuration."""

    type: Literal["mimo"] = "mimo"
    model: str = Field(
        default="mimo-v2.5-tts",
        description="MiMo speech synthesis model name",
    )
    base_url: str = Field(
        default="https://api.xiaomimimo.com/v1",
        description="MiMo OpenAI-compatible API base URL",
    )
    voice: str = Field(
        default="mimo_default",
        description="MiMo voice ID",
    )
    response_format: str = Field(
        default="wav",
        description="Audio format requested from MiMo, for example wav or mp3",
    )
    style_prompt: str | None = Field(
        default=None,
        description="Optional user-style prompt used before the assistant synthesis text",
    )
    timeout: float = Field(
        default=60.0,
        gt=0,
        description="HTTP timeout in seconds",
    )
