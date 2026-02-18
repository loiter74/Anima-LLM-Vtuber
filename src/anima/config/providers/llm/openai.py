"""OpenAI LLM 提供者配置"""

from typing import Optional, Literal
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register("llm", "openai")
class OpenAILLMConfig(LLMBaseConfig):
    """OpenAI LLM 配置"""
    type: Literal["openai"] = "openai"
    model: str = Field(default="gpt-4o-mini", description="模型名称")
    base_url: Optional[str] = Field(default=None, description="API Base URL")
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)