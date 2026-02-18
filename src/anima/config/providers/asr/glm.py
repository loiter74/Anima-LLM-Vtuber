"""智谱 AI GLM ASR 提供者配置"""

from typing import Literal
from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register("asr", "glm")
class GLMASRConfig(ASRBaseConfig):
    """智谱 AI GLM ASR 配置"""
    type: Literal["glm"] = "glm"
    model: str = Field(default="glm-asr", description="ASR 模型名称")
    stream: bool = Field(default=False, description="是否流式识别")
