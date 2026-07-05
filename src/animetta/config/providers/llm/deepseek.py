"""DeepSeek LLM provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register_config("llm", "deepseek")
class DeepSeekLLMConfig(LLMBaseConfig):
    """DeepSeek LLM configuration"""
    type: Literal["deepseek"] = "deepseek"
    model: str = Field(default="deepseek-v4-flash", description="Model name: deepseek-v4-flash / deepseek-v4-pro")
    base_url: str = Field(default="https://api.deepseek.com/v1", description="DeepSeek API Base URL")
    thinking: Literal["enabled", "disabled"] = Field(
        default="disabled",
        description="Thinking mode: 'enabled' or 'disabled'. Flash realtime roleplay should use 'disabled'.",
    )
