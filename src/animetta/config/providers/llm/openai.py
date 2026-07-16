"""OpenAI LLM provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register_config("llm", "openai")
class OpenAILLMConfig(LLMBaseConfig):
    """OpenAI LLM configuration"""

    type: Literal["openai"] = "openai"
    model: str = Field(default="gpt-4o-mini", description="Model name")
    base_url: str | None = Field(default=None, description="API Base URL")
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
