"""VibeVoice TTS provider configuration (Microsoft open-source long-form multi-speaker TTS)"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register_config("tts", "vibe_voice")
class VibeVoiceTTSConfig(TTSBaseConfig):
    """VibeVoice TTS configuration

    Supports Local (local GPU inference) and Remote (HTTP API) modes.
    Default Remote mode points to local VibeVoice inference service at localhost:8765.
    RTX 5090D can run 1.5B (~6GB VRAM) and 7B (~16GB VRAM) models smoothly.
    """

    type: Literal["vibe_voice"] = "vibe_voice"

    # === Model identifier ===
    model: str = Field(
        default="vibe-voice-1.5b",
        description="Model name identifier (for logging and remote API requests)",
    )

    # === Deployment mode ===
    mode: str = Field(
        default="remote",
        description='Deployment mode: "remote" (HTTP API) or "local" (local subprocess inference)',
    )

    # === Remote mode parameters ===
    base_url: str = Field(
        default="http://localhost:8765",
        description="Remote mode: VibeVoice inference service URL",
    )

    # === Local mode parameters ===
    model_size: str = Field(
        default="1.5b",
        description='Local mode: model size "1.5b" or "7b"',
    )
    model_path: str | None = Field(
        default=None,
        description="Local mode: model weight path (default HuggingFace auto-download)",
    )

    # === Synthesis parameters ===
    num_speakers: int = Field(
        default=1,
        ge=1,
        le=4,
        description="Number of speakers (VibeVoice supports up to 4 speakers)",
    )
    language: str = Field(
        default="zh",
        description='Language: "zh" / "en" / "mix"',
    )
