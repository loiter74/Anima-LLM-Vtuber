"""
LLM (大语言模型) 服务模块
"""

from .interface import LLMInterface
from .factory import LLMFactory

__all__ = ["LLMInterface", "LLMFactory"]