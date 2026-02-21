"""ASR 提供者配置模块"""

from typing import Annotated, Union
from pydantic import Field

from .base import ASRBaseConfig
from .mock import MockASRConfig
from .openai import OpenAIASRConfig
from .glm import GLMASRConfig
from .faster_whisper import FasterWhisperASRConfig

__all__ = [
    "ASRBaseConfig",
    "MockASRConfig",
    "OpenAIASRConfig",
    "GLMASRConfig",
    "FasterWhisperASRConfig",
    "ASRConfig",
]

# Discriminated Union 类型
ASRConfig = Annotated[
    Union[
        MockASRConfig,
        OpenAIASRConfig,
        GLMASRConfig,
        FasterWhisperASRConfig,
    ],
    Field(discriminator="type")
]