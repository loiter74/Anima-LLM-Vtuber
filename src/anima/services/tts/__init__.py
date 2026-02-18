"""
TTS (语音合成) 服务模块
"""

from .interface import TTSInterface
from .factory import TTSFactory

__all__ = ["TTSInterface", "TTSFactory"]