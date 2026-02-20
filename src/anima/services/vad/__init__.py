"""
VAD (语音活动检测) 模块
"""

from .interface import VADInterface, VADState, VADResult
from .factory import VADFactory

# 导入实现以触发 ProviderRegistry 注册
try:
    from .implementations import mock_vad, silero_vad
except ImportError:
    pass

__all__ = [
    "VADInterface",
    "VADState",
    "VADResult",
    "VADFactory",
]