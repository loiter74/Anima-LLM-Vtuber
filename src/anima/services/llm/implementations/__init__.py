"""
Agent 服务实现模块

按需导入，缺少依赖的实现会被跳过
装饰器在模块导入时执行注册
"""

# MockAgent 无外部依赖
from .mock_agent import MockAgent

# GLMAgent 使用 zai-sdk（可选依赖）
try:
    from .glm_agent import GLMAgent
except ImportError:
    GLMAgent = None  # type: ignore

# OllamaAgent 需要 ollama 包（可选依赖）
try:
    from .ollama_agent import OllamaAgent
except ImportError:
    OllamaAgent = None  # type: ignore

# OpenAIAgent 需要 openai 包（可选依赖）
try:
    from .openai_agent import OpenAIAgent
except ImportError:
    OpenAIAgent = None  # type: ignore


def get_agent_class(provider: str):
    """
    获取 Agent 实现类（用于延迟加载）
    
    Args:
        provider: 提供商名称
        
    Returns:
        Agent 类，如果不可用则返回 None
    """
    if provider == "mock":
        return MockAgent
    elif provider == "glm":
        return GLMAgent
    elif provider == "ollama":
        return OllamaAgent
    elif provider == "openai":
        return OpenAIAgent
    return None


__all__ = [
    "MockAgent",
    "GLMAgent",
    "OpenAIAgent",
    "OllamaAgent",
    "get_agent_class",
]
