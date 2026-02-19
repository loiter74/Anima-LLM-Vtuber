"""
VAD (语音活动检测) 接口定义
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Union
from enum import Enum
import numpy as np


class VADState(Enum):
    """VAD 状态枚举"""
    IDLE = 1       # 空闲状态，等待语音
    ACTIVE = 2     # 检测到语音
    INACTIVE = 3   # 语音结束（静音状态）


class VADResult:
    """VAD 检测结果"""
    
    def __init__(
        self,
        audio_data: bytes = b"",
        is_speech_start: bool = False,
        is_speech_end: bool = False,
        state: VADState = VADState.IDLE
    ):
        self.audio_data = audio_data
        self.is_speech_start = is_speech_start
        self.is_speech_end = is_speech_end
        self.state = state
    
    @property
    def is_special_signal(self) -> bool:
        """是否是特殊信号（开始/结束标记）"""
        return self.is_speech_start or self.is_speech_end
    
    def __repr__(self):
        if self.is_speech_start:
            return "<VADResult: SPEECH_START>"
        elif self.is_speech_end:
            return f"<VADResult: SPEECH_END, audio_len={len(self.audio_data)}>"
        else:
            return f"<VADResult: state={self.state.name}, audio_len={len(self.audio_data)}>"


class VADInterface(ABC):
    """
    语音活动检测接口的抽象基类
    所有 VAD 实现都必须继承此类并实现其抽象方法
    """
    
    @abstractmethod
    def detect_speech(self, audio_data: Union[list, np.ndarray]) -> VADResult:
        """
        检测音频数据中的语音活动
        
        Args:
            audio_data: 音频数据（float32 列表或 numpy 数组）
            
        Returns:
            VADResult: 检测结果
        """
        pass
    
    @abstractmethod
    def reset(self) -> None:
        """重置 VAD 状态机"""
        pass
    
    @abstractmethod
    def get_current_state(self) -> VADState:
        """获取当前状态"""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """清理资源"""
        pass