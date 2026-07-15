"""Silero VAD configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import VADBaseConfig


@ProviderRegistry.register_config("vad", "silero")
class SileroVADConfig(VADBaseConfig):
    """Silero VAD configuration

    Default values match the canonical runtime manifest declaration.
    """
    type: Literal["silero"] = "silero"
    prob_threshold: float = Field(default=0.15, description="Speech probability threshold")
    db_threshold: float = Field(default=-100, description="Decibel threshold")
    required_hits: int = Field(default=6, description="Consecutive hits required to start speech")
    required_misses: int = Field(default=2, description="Consecutive misses required to stop speech")
    smoothing_window: int = Field(default=12, description="Smoothing window size")
