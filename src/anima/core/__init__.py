"""
核心抽象层
定义 Pipeline 和 EventBus 的基础类型
"""

from .types import (
    WebSocketSend,
    ConversationResult,
)
from .context import PipelineContext
from .events import OutputEvent, SinkMessage, EventType, ControlSignal

__all__ = [
    # Types
    "WebSocketSend",
    "ConversationResult",
    # Context
    "PipelineContext",
    # Events
    "OutputEvent",
    "SinkMessage",
    "EventType",
    "ControlSignal",
]