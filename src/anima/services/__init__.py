"""
服务模块
按服务种类组织：
- asr: 语音识别服务
- tts: 语音合成服务
- agent: LLM 代理服务
"""

from .asr import ASRInterface
from .tts import TTSInterface
from .agent import AgentInterface

__all__ = ["ASRInterface", "TTSInterface", "AgentInterface"]