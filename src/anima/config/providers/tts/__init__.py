"""TTS 提供者配置模块"""

from typing import Annotated, Union
from pydantic import Field

from .base import TTSBaseConfig
from .mock import MockTTSConfig
from .openai import OpenAITTSConfig
from .edge import EdgeTTSConfig
from .glm import GLMTTSConfig

__all__ = [
    "TTSBaseConfig",
    "MockTTSConfig",
    "OpenAITTSConfig",
    "EdgeTTSConfig",
    "GLMTTSConfig",
    "TTSConfig",
]

# Discriminated Union 类型
TTSConfig = Annotated[
    Union[MockTTSConfig, OpenAITTSConfig, EdgeTTSConfig, GLMTTSConfig],
    Field(discriminator="type")
]