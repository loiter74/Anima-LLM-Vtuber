"""Mock LLM provider configuration"""

from typing import Literal

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register_config("llm", "mock")
class MockLLMConfig(LLMBaseConfig):
    """Mock LLM configuration - for testing"""

    type: Literal["mock"] = "mock"
