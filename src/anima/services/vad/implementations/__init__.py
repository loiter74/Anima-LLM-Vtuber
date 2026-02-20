"""
VAD 实现模块
"""

from .silero_vad import SileroVAD
from .mock_vad import MockVAD

__all__ = [
    "SileroVAD",
    "MockVAD",
]