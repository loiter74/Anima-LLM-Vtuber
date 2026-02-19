"""
核心类型定义
定义系统的共享数据类型
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional, Dict


# WebSocket 发送函数类型
WebSocketSend = Callable[[str], Awaitable[None]]


@dataclass
class ConversationResult:
    """
    对话结果
    
    一次对话 turn 的完整结果
    """
    # 完整的响应文本
    full_response: str = ""
    
    # 是否被打断
    interrupted: bool = False
    
    # 用户听到的部分（被打断时）
    heard_response: str = ""
    
    # 错误信息（如果出错）
    error: Optional[str] = None
    
    # 额外元数据
    metadata: Dict[str, Any] = field(default_factory=dict)