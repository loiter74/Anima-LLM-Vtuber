"""Zhipu AI GLM LLM provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register_config("llm", "glm")
class GLMLLMConfig(LLMBaseConfig):
    """Zhipu AI GLM configuration"""

    type: Literal["glm"] = "glm"
    model: str = Field(default="glm-4-flash", description="Model name")
    enable_thinking: bool = Field(default=False, description="Enable deep thinking mode")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retry count")
    retry_delay: float = Field(default=1.0, ge=0, le=10, description="Retry delay (seconds)")
    timeout: int = Field(default=60, ge=5, le=300, description="Request timeout (seconds)")
