"""ASR 提供者配置模块"""

from typing import Annotated, Union
from pydantic import Field

from .base import ASRBaseConfig
from .mock import MockASRConfig
from .openai import OpenAIASRConfig
from .glm import GLMASRConfig

__all__ = [
    "ASRBaseConfig",
    "MockASRConfig",
    "OpenAIASRConfig",
    "GLMASRConfig",
    "ASRConfig",
]

# Discriminated Union 类型
ASRConfig = Annotated[
    Union[MockASRConfig, OpenAIASRConfig, GLMASRConfig],
    Field(discriminator="type")
]