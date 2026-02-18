"""LLM 提供者配置模块"""

from typing import Annotated, Union
from pydantic import Field

from .base import LLMBaseConfig
from .mock import MockLLMConfig
from .openai import OpenAILLMConfig
from .glm import GLMLLMConfig
from .ollama import OllamaLLMConfig

# 导出所有配置类
__all__ = [
    "LLMBaseConfig",
    "MockLLMConfig",
    "OpenAILLMConfig",
    "GLMLLMConfig",
    "OllamaLLMConfig",
    "LLMConfig",
]

# Discriminated Union 类型 - Pydantic 会根据 type 字段自动选择正确的类
LLMConfig = Annotated[
    Union[MockLLMConfig, OpenAILLMConfig, GLMLLMConfig, OllamaLLMConfig],
    Field(discriminator="type")
]