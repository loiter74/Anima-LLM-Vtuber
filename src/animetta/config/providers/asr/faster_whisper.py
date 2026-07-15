"""Faster-Whisper ASR provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register_config("asr", "faster_whisper")
class FasterWhisperASRConfig(ASRBaseConfig):
    """Faster-Whisper ASR configuration"""

    type: Literal["faster_whisper"] = "faster_whisper"

    # Model configuration
    model: str = Field(
        default="distil-large-v3",
        description="Whisper model name (tiny/base/small/medium/large-v2/large-v3/distil-*)",
    )

    # Device and performance configuration
    device: str = Field(default="auto", description="Device (auto/cpu/cuda)")

    compute_type: str = Field(
        default="default", description="Compute precision (default/int8/float16/float32)"
    )

    download_root: str | None = Field(default=None, description="Model download directory")

    # Recognition parameters
    beam_size: int = Field(default=5, ge=1, le=10, description="Beam search size")

    vad_filter: bool = Field(default=True, description="Whether to use VAD filtering")

    vad_parameters: dict = Field(
        default_factory=lambda: {
            "min_silence_duration_ms": 500,
            "speech_pad_ms": 30,
        },
        description="VAD parameters",
    )
