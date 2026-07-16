"""Zhipu AI GLM ASR provider configuration"""

from typing import Literal

from pydantic import Field

from ...core.registry import ProviderRegistry
from .base import ASRBaseConfig


@ProviderRegistry.register_config("asr", "glm")
class GLMASRConfig(ASRBaseConfig):
    """Zhipu AI GLM ASR configuration"""

    type: Literal["glm"] = "glm"
    model: str = Field(default="glm-asr", description="ASR model name")
    stream: bool = Field(default=False, description="Whether to use streaming recognition")
