"""Ollama LLM 提供者配置"""

from typing import Literal
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register("llm", "ollama")
class OllamaLLMConfig(LLMBaseConfig):
    """Ollama LLM 配置"""
    type: Literal["ollama"] = "ollama"
    model: str = Field(default="llama3", description="模型名称")
    base_url: str = Field(default="http://localhost:11434", description="Ollama 服务地址")