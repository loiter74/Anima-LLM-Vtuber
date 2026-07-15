"""RVC (Retrieval-based Voice Conversion) provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import VCBaseConfig


@ProviderRegistry.register_config("vc", "rvc")
class RVCConfig(VCBaseConfig):
    """RVC voice conversion configuration

    Uses a local RVC model checkpoint and feature index for
    zero-shot voice timbre conversion.
    """

    type: Literal["rvc"] = "rvc"

    # === Model paths ===
    model_path: str = Field(
        default="",
        description="Path to RVC .pth model checkpoint",
    )
    index_path: str = Field(
        default="",
        description="Path to RVC .index faiss feature index file (optional, for retrieval-based conversion)",
    )

    # === Conversion parameters ===
    index_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Feature index retrieval rate (0.0 = no retrieval, 1.0 = full retrieval)",
    )
    f0_method: str = Field(
        default="rmvpe",
        description="F0 extraction method: harvest | pm | crepe | rmvpe | fcpe",
    )
    key: int = Field(
        default=0,
        ge=-24,
        le=24,
        description="Pitch shift in semitones (positive = higher pitch)",
    )
    formant: int = Field(
        default=0,
        ge=-12,
        le=12,
        description="Formant shift for voice character adjustment",
    )
    rms_mix_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="RMS mix rate for volume envelope blending",
    )
    protect: float = Field(
        default=0.33,
        ge=0.0,
        le=1.0,
        description="Protection rate for unvoiced consonants and breath sounds",
    )
    hop_length: int = Field(
        default=128,
        description="Hop length for audio processing",
    )
    f0_min: int = Field(
        default=50,
        description="Minimum F0 frequency in Hz",
    )
    f0_max: int = Field(
        default=1100,
        description="Maximum F0 frequency in Hz",
    )
    sample_rate: int = Field(
        default=40000,
        description="RVC model native sample rate (usually 40kHz for 48k models)",
    )
