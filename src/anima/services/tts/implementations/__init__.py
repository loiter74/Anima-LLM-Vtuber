"""
TTS 服务实现模块
"""

from .mock_tts import MockTTS
from .glm_tts import GLMTTS

__all__ = ["MockTTS", "GLMTTS"]
