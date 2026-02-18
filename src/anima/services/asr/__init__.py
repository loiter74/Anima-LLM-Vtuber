"""
ASR (语音识别) 服务模块
"""

from .interface import ASRInterface
from .factory import ASRFactory

__all__ = ["ASRInterface", "ASRFactory"]