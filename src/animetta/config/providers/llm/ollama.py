"""Ollama LLM provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register_config("llm", "ollama")
class OllamaLLMConfig(LLMBaseConfig):
    """Ollama LLM configuration"""

    type: Literal["ollama"] = "ollama"
    model: str = Field(default="llama3", description="Model name")
    base_url: str = Field(default="http://localhost:11434", description="Ollama service URL")
