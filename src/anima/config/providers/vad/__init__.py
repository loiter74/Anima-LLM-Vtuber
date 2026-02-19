"""VAD 提供者配置模块"""

from typing import Annotated, Union
from pydantic import Field

from .base import VADBaseConfig
from .mock import MockVADConfig
from .silero import SileroVADConfig

__all__ = [
    "VADBaseConfig",
    "MockVADConfig",
    "SileroVADConfig",
    "VADConfig",
]

# Discriminated Union 类型
VADConfig = Annotated[
    Union[MockVADConfig, SileroVADConfig],
    Field(discriminator="type")
]