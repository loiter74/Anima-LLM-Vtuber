"""
事件类型定义
定义 EventBus 中使用的事件类型
"""

from dataclasses import dataclass, field
from typing import Any, Dict
from enum import Enum


class EventType(str, Enum):
    """事件类型枚举"""
    SENTENCE = "sentence"           # 文本句子
    AUDIO = "audio"                 # 音频数据
    TOOL_CALL = "tool_call"         # 工具调用
    CONTROL = "control"             # 控制信号
    IMAGE = "image"                 # 图片
    GAME_CONTROL = "game_control"   # 游戏控制
    ERROR = "error"                 # 错误
    EXPRESSION = "expression"       # Live2D 表情


class ControlSignal(str, Enum):
    """控制信号枚举"""
    CONVERSATION_START = "conversation-start"
    CONVERSATION_END = "conversation-end"
    ASR_START = "asr-start"
    SYNTH_COMPLETE = "backend-synth-complete"
    INTERRUPT = "interrupt"
    INTERRUPTED = "interrupted"
    START_MIC = "start-mic"
    STOP_MIC = "stop-mic"


@dataclass
class OutputEvent:
    """
    输出事件
    
    统一的输出事件类型，由 Pipeline 产出，分发到各个 Handler 处理
    """
    # 事件类型
    type: str
    
    # 事件数据（根据 type 不同而不同）
    data: Any
    
    # 序号（用于排序）
    seq: int = 0
    
    # 额外元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "type": self.type,
            "data": self.data,
            "seq": self.seq,
            "metadata": self.metadata,
        }


@dataclass
class SinkMessage:
    """
    输出槽消息
    
    由 Handler 产出，发送到 WebSocket
    """
    # 消息类型
    type: str
    
    # 消息内容（将被 JSON 序列化）
    content: Dict[str, Any]
    
    # 序号（用于排序）
    seq: int = 0
    
    # 优先级（数字越小优先级越高）
    priority: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为发送格式"""
        result = {"type": self.type}
        result.update(self.content)
        return result