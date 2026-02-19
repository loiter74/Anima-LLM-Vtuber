"""
音频缓冲区管理器
用于累积音频数据并在对话触发时提供完整音频
"""

import numpy as np
from typing import Dict, Optional
from loguru import logger


class AudioBufferManager:
    """
    管理每个会话的音频缓冲区
    
    支持累积音频数据、获取完整音频、清空缓冲区等操作
    参考 Open-LLM-VTuber 的 received_data_buffers 实现
    """
    
    def __init__(self):
        # 存储每个会话的音频缓冲区
        # 键: session_id, 值: numpy 数组
        self._buffers: Dict[str, np.ndarray] = {}
        
        # 音频配置
        self.sample_rate = 16000  # 默认采样率
    
    def append(self, session_id: str, audio_data: list) -> int:
        """
        向指定会话的缓冲区追加音频数据
        
        Args:
            session_id: 会话 ID
            audio_data: 音频数据列表（float32 格式）
            
        Returns:
            int: 当前缓冲区中的采样点数量
        """
        if session_id not in self._buffers:
            self._buffers[session_id] = np.array([], dtype=np.float32)
        
        # 将音频数据追加到缓冲区
        audio_np = np.array(audio_data, dtype=np.float32)
        self._buffers[session_id] = np.append(
            self._buffers[session_id], 
            audio_np
        )
        
        return len(self._buffers[session_id])
    
    def get(self, session_id: str) -> Optional[np.ndarray]:
        """
        获取指定会话的完整音频数据
        
        Args:
            session_id: 会话 ID
            
        Returns:
            Optional[np.ndarray]: 音频数据，如果不存在则返回 None
        """
        return self._buffers.get(session_id)
    
    def get_duration(self, session_id: str) -> float:
        """
        获取指定会话缓冲区中音频的时长（秒）
        
        Args:
            session_id: 会话 ID
            
        Returns:
            float: 音频时长（秒）
        """
        buffer = self._buffers.get(session_id)
        if buffer is None or len(buffer) == 0:
            return 0.0
        return len(buffer) / self.sample_rate
    
    def clear(self, session_id: str) -> None:
        """
        清空指定会话的缓冲区
        
        Args:
            session_id: 会话 ID
        """
        if session_id in self._buffers:
            self._buffers[session_id] = np.array([], dtype=np.float32)
            logger.debug(f"已清空会话 {session_id} 的音频缓冲区")
    
    def pop(self, session_id: str) -> Optional[np.ndarray]:
        """
        获取并清空指定会话的音频数据
        
        Args:
            session_id: 会话 ID
            
        Returns:
            Optional[np.ndarray]: 音频数据，获取后缓冲区会被清空
        """
        audio_data = self._buffers.get(session_id)
        if audio_data is not None:
            self._buffers[session_id] = np.array([], dtype=np.float32)
        return audio_data
    
    def remove(self, session_id: str) -> None:
        """
        完全移除指定会话的缓冲区（用于会话断开时）
        
        Args:
            session_id: 会话 ID
        """
        if session_id in self._buffers:
            del self._buffers[session_id]
            logger.debug(f"已移除会话 {session_id} 的音频缓冲区")
    
    def exists(self, session_id: str) -> bool:
        """
        检查指定会话是否有缓冲区
        
        Args:
            session_id: 会话 ID
            
        Returns:
            bool: 是否存在缓冲区
        """
        return session_id in self._buffers and len(self._buffers[session_id]) > 0
    
    def get_all_session_ids(self) -> list:
        """
        获取所有有缓冲区的会话 ID
        
        Returns:
            list: 会话 ID 列表
        """
        return list(self._buffers.keys())