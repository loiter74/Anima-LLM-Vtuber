"""Mock VAD 配置"""

from typing import Literal
from pydantic import Field
from ...core.registry import ProviderRegistry
from .base import VADBaseConfig


@ProviderRegistry.register_config("vad", "mock")
class MockVADConfig(VADBaseConfig):
    """Mock VAD 配置（用于测试）"""
    type: Literal["mock"] = "mock"
    sample_rate: int = Field(default=16000, description="采样率")
    db_threshold: float = Field(default=-30.0, description="分贝阈值")
    min_speech_duration: int = Field(default=5, description="最小语音帧数")
    min_silence_duration: int = Field(default=15, description="最小静音帧数")