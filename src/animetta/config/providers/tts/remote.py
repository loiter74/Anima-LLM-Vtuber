"""Configuration for an independently deployed TTS service."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


class RemoteTTSWorkerConfig(BaseModel):
    """Pinned worker identity and generation settings used by deployment tooling."""

    revision: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    device: str = "cuda"
    dtype: str = "bfloat16"
    language: str = "Chinese"
    use_flash_attn: bool = False
    max_new_tokens: int = Field(default=512, ge=1, le=512)
    warmup_max_new_tokens: int = Field(default=48, ge=1, le=64)
    temperature: float = Field(default=0.9, ge=0)
    top_p: float = Field(default=1.0, ge=0, le=1)
    repetition_penalty: float = Field(default=1.05, gt=0)
    ref_audio_path: str = Field(min_length=1)
    ref_text: str = Field(min_length=1)
    x_vector_only: bool = False

    model_config = ConfigDict(extra="forbid", frozen=True)


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
    worker: RemoteTTSWorkerConfig | None = None
