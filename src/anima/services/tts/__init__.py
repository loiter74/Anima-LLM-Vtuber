"""
TTS (语音合成) 服务模块
"""

from .interface import TTSInterface
from .factory import TTSFactory

# 导入实现以触发 ProviderRegistry 注册
try:
    from .implementations import mock_tts, glm_tts
except ImportError:
    pass

__all__ = ["TTSInterface", "TTSFactory"]