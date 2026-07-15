"""Mock VAD configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import VADBaseConfig


@ProviderRegistry.register_config("vad", "mock")
class MockVADConfig(VADBaseConfig):
    """Mock VAD configuration (for testing)"""

    type: Literal["mock"] = "mock"
    sample_rate: int = Field(default=16000, description="Sample rate")
    db_threshold: float = Field(default=-30.0, description="Decibel threshold")
    min_speech_duration: int = Field(default=5, description="Minimum speech frame count")
    min_silence_duration: int = Field(default=15, description="Minimum silence frame count")
