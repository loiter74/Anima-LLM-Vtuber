"""Mock LLM 提供者配置"""

from typing import Literal

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register("llm", "mock")
class MockLLMConfig(LLMBaseConfig):
    """Mock LLM 配置 - 用于测试"""
    type: Literal["mock"] = "mock"