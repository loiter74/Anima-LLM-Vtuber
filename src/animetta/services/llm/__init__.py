"""LLM service implementation module.

Import on demand; implementations with missing dependencies are skipped.
Decorators execute registration at module import time.
"""

from __future__ import annotations

from importlib import import_module

from .factory import LLMFactory
from .interface import LLMInterface

# MockLLM has no external dependencies
from .mock_llm import MockLLM
from .stream_handler import OpenAIStreamHandler
from .tool_handler import OpenAIToolHandler

_LAZY_PROVIDERS = {
    "GLMLLM": (".glm_llm", "GLMLLM"),
    "OllamaLLM": (".ollama_llm", "OllamaLLM"),
    "OpenAILLM": (".openai_llm", "OpenAILLM"),
    "LocalLoraLLM": (".local_lora_llm", "LocalLoraLLM"),
}


def __getattr__(name: str):
    """Import optional provider implementations only when requested."""
    target = _LAZY_PROVIDERS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    try:
        value = getattr(import_module(module_name, __name__), attribute)
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("animetta."):
            raise
        return None
    globals()[name] = value
    return value


def get_llm_class(provider: str) -> type[LLMInterface] | None:
    """
    Get the LLM implementation class (for lazy loading)

    Args:
        provider: Provider name

    Returns:
        LLM class, or None if unavailable
    """
    attribute = {
        "mock": "MockLLM",
        "glm": "GLMLLM",
        "ollama": "OllamaLLM",
        "openai": "OpenAILLM",
        "deepseek": "OpenAILLM",
        "local_lora": "LocalLoraLLM",
    }.get(provider)
    if attribute is None:
        return None
    if attribute == "MockLLM":
        return MockLLM
    return __getattr__(attribute)


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
