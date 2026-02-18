"""
ASR 服务实现模块
"""

from .mock_asr import MockASR
from .glm_asr import GLMASR

__all__ = ["MockASR", "GLMASR"]
