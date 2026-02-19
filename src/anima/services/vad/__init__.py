"""
VAD (语音活动检测) 模块
"""

from .interface import VADInterface, VADState, VADResult
from .factory import VADFactory

__all__ = [
    "VADInterface",
    "VADState",
    "VADResult",
    "VADFactory",
]