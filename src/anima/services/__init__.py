"""
服务模块

按服务种类组织：
- llm: LLM 代理服务
- asr: 语音识别服务
- tts: 语音合成服务
- vad: 语音活动检测
"""

from .llm import LLMInterface, LLMFactory
from .asr import ASRInterface, ASRFactory
from .tts import TTSInterface, TTSFactory
from .vad import VADInterface, VADFactory

# 兼容性别名
AgentInterface = LLMInterface
AgentFactory = LLMFactory

__all__ = [
    # LLM / Agent
    "LLMInterface",
    "LLMFactory",
    "AgentInterface",
    "AgentFactory",
    # ASR
    "ASRInterface",
    "ASRFactory",
    # TTS
    "TTSInterface",
    "TTSFactory",
    # VAD
    "VADInterface",
    "VADFactory",
]
