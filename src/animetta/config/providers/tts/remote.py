"""Configuration for an independently deployed TTS service."""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "remote")
class RemoteTTSConfig(TTSBaseConfig):
    """Application-side client configuration for a remote TTS worker."""

    type: Literal["remote"] = "remote"
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    response_format: Literal["wav", "mp3", "opus"] = "wav"
    language: str | None = None
    timeout_seconds: float = Field(default=20.0, gt=0)
    revision: str | None = Field(default=None, min_length=1)
    quantization: str | None = Field(default=None, min_length=1)
    runtime_commit: str | None = Field(default=None, min_length=1)
