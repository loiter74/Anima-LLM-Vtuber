"""LLM provider configuration — discriminated union for YAML deserialization."""

from ...core.registry import ProviderRegistry

# Import all implementations so their @register_config decorators fire
from .base import LLMBaseConfig  # noqa: F401 — triggers registration chain
from .deepseek import DeepSeekLLMConfig  # noqa: F401
from .glm import GLMLLMConfig  # noqa: F401
from .local_lora_llm import LocalLoraLLMConfig  # noqa: F401
from .mock import MockLLMConfig  # noqa: F401
from .ollama import OllamaLLMConfig  # noqa: F401
from .openai import OpenAILLMConfig  # noqa: F401

# Discriminated Union type — auto-generated from registered configs
LLMConfig = ProviderRegistry.create_union_type("llm")

__all__ = [
    "LLMBaseConfig",
    "LLMConfig",
]
