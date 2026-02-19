"""
Mock VAD 实现（用于测试）
"""

from typing import Union
import numpy as np
from loguru import logger

from ..interface import VADInterface, VADState, VADResult


class MockVAD(VADInterface):
    """
    Mock VAD 实现
    
    简单的基于音量的语音活动检测，用于测试
    不需要额外依赖
    """
    
    def __init__(
        self,
        sample_rate: int = 16000,
        db_threshold: float = -30.0,
        min_speech_duration: int = 5,
        min_silence_duration: int = 15,
    ):
        self.sample_rate = sample_rate
        self.db_threshold = db_threshold
        self.min_speech_duration = min_speech_duration
        self.min_silence_duration = min_silence_duration
        
        # 状态
        self.state = VADState.IDLE
        self.speech_frames = 0
        self.silence_frames = 0
        
        # 累积的音频
        self.audio_buffer = bytearray()
        
        # 预缓冲
        self.pre_buffer = []
        self.pre_buffer_max = 10
        
        logger.info(f"Mock VAD 初始化: db_threshold={db_threshold}")
    
    def _calculate_db(self, audio_data: np.ndarray) -> float:
        """计算音频的分贝值"""
        rms = np.sqrt(np.mean(np.square(audio_data)))
        return 20 * np.log10(rms + 1e-7) if rms > 0 else -np.inf
    
    def detect_speech(self, audio_data: Union[list, np.ndarray]) -> VADResult:
        """
        检测音频数据中的语音活动
        
        基于简单的音量阈值判断
        """
        # 转换为 numpy 数组
        audio_np = np.array(audio_data, dtype=np.float32)
        
        # 计算分贝值
        db = self._calculate_db(audio_np)
        is_loud = db > self.db_threshold
        
        # 转换为字节
        int_audio = (audio_np * 32767).astype(np.int16)
        chunk_bytes = int_audio.tobytes()
        
        # 状态机
        if self.state == VADState.IDLE:
            # 预缓冲
            self.pre_buffer.append(chunk_bytes)
            if len(self.pre_buffer) > self.pre_buffer_max:
                self.pre_buffer.pop(0)
            
            if is_loud:
                self.speech_frames += 1
                if self.speech_frames >= self.min_speech_duration:
                    self.state = VADState.ACTIVE
                    self.speech_frames = 0
                    self.silence_frames = 0
                    self.audio_buffer.extend(chunk_bytes)
                    
                    return VADResult(
                        audio_data=b"",
                        is_speech_start=True,
                        is_speech_end=False,
                        state=VADState.ACTIVE
                    )
            else:
                self.speech_frames = 0
        
        elif self.state == VADState.ACTIVE:
            self.audio_buffer.extend(chunk_bytes)
            
            if is_loud:
                self.silence_frames = 0
            else:
                self.silence_frames += 1
                if self.silence_frames >= self.min_silence_duration:
                    self.state = VADState.IDLE
                    self.silence_frames = 0
                    self.speech_frames = 0
                    
                    # 合并预缓冲和主缓冲区
                    pre_bytes = b"".join(self.pre_buffer)
                    audio_data = pre_bytes + bytes(self.audio_buffer)
                    
                    self.audio_buffer.clear()
                    self.pre_buffer.clear()
                    
                    return VADResult(
                        audio_data=audio_data,
                        is_speech_start=False,
                        is_speech_end=True,
                        state=VADState.IDLE
                    )
        
        return VADResult(
            audio_data=b"",
            is_speech_start=False,
            is_speech_end=False,
            state=self.state
        )
    
    def reset(self) -> None:
        """重置状态"""
        self.state = VADState.IDLE
        self.speech_frames = 0
        self.silence_frames = 0
        self.audio_buffer.clear()
        self.pre_buffer.clear()
        logger.debug("Mock VAD 已重置")
    
    def get_current_state(self) -> VADState:
        """获取当前状态"""
        return self.state
    
    async def close(self) -> None:
        """清理资源"""
        self.reset()
        logger.info("Mock VAD 资源已释放")