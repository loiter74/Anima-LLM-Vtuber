"""LLM service implementation module.

Import on demand; implementations with missing dependencies are skipped.
Decorators execute registration at module import time.
"""

from __future__ import annotations

from .factory import LLMFactory
from .interface import LLMInterface

# MockLLM has no external dependencies
from .mock_llm import MockLLM
from .stream_handler import OpenAIStreamHandler
from .tool_handler import OpenAIToolHandler

# GLMLLM uses zai-sdk (optional dependency)
try:
    from .glm_llm import GLMLLM
except ImportError:
    GLMLLM = None  # type: ignore

# OllamaLLM requires the ollama package (optional dependency)
try:
    from .ollama_llm import OllamaLLM
except ImportError:
    OllamaLLM = None  # type: ignore

# OpenAILLM requires the openai package (optional dependency)
try:
    from .openai_llm import OpenAILLM
except ImportError:
    OpenAILLM = None  # type: ignore

# LocalLoraLLM requires transformers and peft (optional dependencies)
try:
    from .local_lora_llm import LocalLoraLLM
except ImportError:
    LocalLoraLLM = None  # type: ignore


def get_llm_class(provider: str):
    """
    Get the LLM implementation class (for lazy loading)

    Args:
        provider: Provider name

    Returns:
        LLM class, or None if unavailable
    """
    if provider == "mock":
        return MockLLM
    elif provider == "glm":
        return GLMLLM
    elif provider == "ollama":
        return OllamaLLM
    elif provider == "openai" or provider == "deepseek":
        return OpenAILLM
    elif provider == "local_lora":
        return LocalLoraLLM
    return None


__all__ = [
    "LLMInterface",
    "LLMFactory",
    "MockLLM",
    "GLMLLM",
    "OpenAILLM",
    "OllamaLLM",
    "LocalLoraLLM",
    "OpenAIStreamHandler",
    "OpenAIToolHandler",
    "get_llm_class",
]
