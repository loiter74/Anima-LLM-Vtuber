"""VAD 基础配置"""

from typing import Literal
from ...core.base import BaseConfig


class VADBaseConfig(BaseConfig):
    """VAD 配置基类"""
    type: str = "base"
    sample_rate: int = 16000