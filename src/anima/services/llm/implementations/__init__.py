"""
LLM 服务实现模块

按需导入，缺少依赖的实现会被跳过
装饰器在模块导入时执行注册
"""

# MockLLM 无外部依赖
from .mock_llm import MockLLM

# GLMLLM 使用 zai-sdk（可选依赖）
try:
    from .glm_llm import GLMLLM
except ImportError:
    GLMLLM = None  # type: ignore

# OllamaLLM 需要 ollama 包（可选依赖）
try:
    from .ollama_llm import OllamaLLM
except ImportError:
    OllamaLLM = None  # type: ignore

# OpenAILLM 需要 openai 包（可选依赖）
try:
    from .openai_llm import OpenAILLM
except ImportError:
    OpenAILLM = None  # type: ignore


def get_llm_class(provider: str):
    """
    获取 LLM 实现类（用于延迟加载）

    Args:
        provider: 提供商名称

    Returns:
        LLM 类，如果不可用则返回 None
    """
    if provider == "mock":
        return MockLLM
    elif provider == "glm":
        return GLMLLM
    elif provider == "ollama":
        return OllamaLLM
    elif provider == "openai":
        return OpenAILLM
    return None


__all__ = [
    "MockLLM",
    "GLMLLM",
    "OpenAILLM",
    "OllamaLLM",
    "get_llm_class",
]
