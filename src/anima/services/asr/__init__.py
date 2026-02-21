"""
ASR (语音识别) 服务模块
"""

from .interface import ASRInterface
from .factory import ASRFactory

# 导入实现以触发 ProviderRegistry 注册
try:
    from .implementations import mock_asr, glm_asr, faster_whisper_asr
except ImportError:
    pass

__all__ = ["ASRInterface", "ASRFactory"]