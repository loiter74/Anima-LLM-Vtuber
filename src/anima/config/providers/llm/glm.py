"""智谱 AI GLM LLM 提供者配置"""

from typing import Literal
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import LLMBaseConfig


@ProviderRegistry.register("llm", "glm")
class GLMLLMConfig(LLMBaseConfig):
    """智谱 AI GLM 配置"""
    type: Literal["glm"] = "glm"
    model: str = Field(default="glm-4-flash", description="模型名称")
    enable_thinking: bool = Field(default=False, description="启用深度思考模式")