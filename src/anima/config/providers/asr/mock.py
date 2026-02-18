"""Mock ASR 提供者配置"""

from typing import Literal

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register("asr", "mock")
class MockASRConfig(ASRBaseConfig):
    """Mock ASR 配置 - 用于测试"""
    type: Literal["mock"] = "mock"