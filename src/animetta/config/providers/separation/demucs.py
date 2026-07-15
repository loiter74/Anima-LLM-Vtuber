"""Demucs / MDX-based audio source separation provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import SeparationBaseConfig


@ProviderRegistry.register_config("separation", "demucs")
class DemucsSeparationConfig(SeparationBaseConfig):
    """Demucs / Mel-Band RoFormer source separation configuration

    Uses a pre-trained Music Source Separation model for stem separation.
    Supports vocal/instrumental separation and multi-stem decomposition.
    """

    type: Literal["demucs"] = "demucs"

    # === Model configuration ===
    model_type: str = Field(
        default="mel_band_roformer",
        description="Model architecture: mel_band_roformer | hdemucs | scnet | apollo",
    )
    config_path: str = Field(
        default="",
        description="Path to model configuration YAML file",
    )
    checkpoint_path: str = Field(
        default="",
        description="Path to model checkpoint file (.ckpt)",
    )

    # === Inference parameters ===
    chunk_size: int = Field(
        default=131584,
        description="Chunk size for processing long audio (in samples)",
    )
    num_overlap: int = Field(
        default=4,
        description="Number of overlapping chunks for smoother transitions",
    )
    batch_size: int = Field(
        default=1,
        description="Batch size for inference",
    )
    normalize: bool = Field(
        default=True,
        description="Normalize audio before processing",
    )
    is_half: bool = Field(
        default=True,
        description="Use FP16 half precision for inference",
    )

    # === Output configuration ===
    instruments: list[str] = Field(
        default=["vocals", "other"],
        description="Instruments/stems to extract from the mixture",
    )
    primary_stem: str | None = Field(
        default=None,
        description="Primary stem for single-stem extraction (e.g., 'vocals')",
    )
