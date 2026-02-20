"""
LLM (大语言模型) 服务模块
"""

from .interface import LLMInterface
from .factory import LLMFactory

# 导入实现以触发 ProviderRegistry 注册
try:
    from .implementations import mock_agent, glm_agent
except ImportError:
    pass

__all__ = ["LLMInterface", "LLMFactory"]