"""Silero VAD 配置"""

from typing import Literal
from pydantic import Field
from ...core.registry import ProviderRegistry
from .base import VADBaseConfig


@ProviderRegistry.register_config("vad", "silero")
class SileroVADConfig(VADBaseConfig):
    """Silero VAD 配置"""
    type: Literal["silero"] = "silero"
    sample_rate: int = Field(default=16000, description="采样率")
    prob_threshold: float = Field(default=0.4, description="语音概率阈值")
    db_threshold: int = Field(default=60, description="分贝阈值")
    required_hits: int = Field(default=3, description="开始说话需要的连续命中次数")
    required_misses: int = Field(default=24, description="停止说话需要的连续未命中次数")
    smoothing_window: int = Field(default=5, description="平滑窗口大小")