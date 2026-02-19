"""
状态管理模块

管理对话过程中的运行时状态：
- AudioBufferManager: 音频缓冲区管理
- TTSTaskManager: TTS 任务管理
- SessionState: 会话状态
"""

from .audio_buffer import AudioBufferManager
from .tts_task_manager import TTSTaskManager

__all__ = [
    "AudioBufferManager",
    "TTSTaskManager",
]