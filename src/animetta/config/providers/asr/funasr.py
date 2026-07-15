"""FunASR Paraformer ASR provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register_config("asr", "funasr")
class FunASRConfig(ASRBaseConfig):
    """FunASR Paraformer configuration

    FunASR is Alibaba's open-source speech recognition toolkit, supporting:
    - paraformer-zh: Chinese offline speech recognition (recommended)
    - paraformer-zh-streaming: Chinese streaming speech recognition
    - paraformer-en: English speech recognition

    Features:
    - Higher Chinese recognition accuracy than Whisper
    - Supports real-time streaming recognition
    - Optional VAD, punctuation restoration, speaker diarization
    """

    type: Literal["funasr"] = "funasr"

    # Model configuration
    model: str = Field(
        default="paraformer-zh",
        description="FunASR model name (paraformer-zh/paraformer-zh-streaming/paraformer-en)",
    )

    # Optional auxiliary models
    vad_model: str | None = Field(
        default="fsmn-vad", description="VAD model (fsmn-vad), set to null to disable"
    )

    punc_model: str | None = Field(
        default="ct-punc",
        description="Punctuation restoration model (ct-punc), set to null to disable",
    )

    spk_model: str | None = Field(
        default=None, description="Speaker diarization model (cam++), set to null to disable"
    )

    # Device configuration
    device: str = Field(default="cuda", description="Device (cpu/cuda)")

    ncpu: int = Field(default=4, ge=1, description="Number of CPU threads (for computation)")

    # Streaming recognition parameters
    chunk_size: list[int] = Field(
        default_factory=lambda: [0, 10, 5],
        description="Streaming chunk size [0, 10, 5] means first chunk 0s, subsequent chunks 10s with 5s overlap",
    )

    # Hotword feature
    hotword: str | None = Field(default=None, description="Hotword file path or hotword string")

    # Model cache directory
    model_hub: str = Field(
        default="ms",  # ms = ModelScope, hf = HuggingFace
        description="Model download source (ms=ModelScope, hf=HuggingFace)",
    )

    disable_update: bool = Field(default=True, description="Disable model auto-update check")
