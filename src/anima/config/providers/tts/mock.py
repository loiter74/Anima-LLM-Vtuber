"""Mock TTS 提供者配置"""

from typing import Literal

from ...core.registry import ProviderRegistry
from .base import TTSBaseConfig


@ProviderRegistry.register("tts", "mock")
class MockTTSConfig(TTSBaseConfig):
    """Mock TTS 配置 - 用于测试"""
    type: Literal["mock"] = "mock"