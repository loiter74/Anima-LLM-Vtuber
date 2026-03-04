"""
Handler 基类
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from loguru import logger

if TYPE_CHECKING:
    from anima.core import OutputEvent, WebSocketSend


class BaseHandler(ABC):
    """
    Handler 抽象基类
    
    处理特定类型的事件
    
    使用示例:
        class MyHandler(BaseHandler):
            async def handle(self, event: OutputEvent) -> None:
                print(f"Received: {event.data}")
    """
    
    def __init__(self, websocket_send: "WebSocketSend" = None):
        """
        初始化 Handler
        
        Args:
            websocket_send: WebSocket 发送函数
        """
        self.websocket_send = websocket_send
    
    @property
    def name(self) -> str:
        """Handler 名称"""
        return self.__class__.__name__.replace("Handler", "").lower()
    
    @abstractmethod
    async def handle(self, event: "OutputEvent") -> None:
        """
        处理事件
        
        Args:
            event: 输出事件
        """
        pass
    
    async def send(self, message: dict) -> None:
        """
        发送消息到 WebSocket
        
        Args:
            message: 消息字典
        """
        if self.websocket_send is None:
            logger.warning(f"{self.name}: WebSocket 未设置，无法发送消息")
            return
        
        import json
        await self.websocket_send(json.dumps(message))