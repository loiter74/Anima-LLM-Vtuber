"""
文本 Handler - 处理文本事件
"""

from typing import TYPE_CHECKING
from loguru import logger

from .base_handler import BaseHandler

if TYPE_CHECKING:
    from anima.core import OutputEvent


class TextHandler(BaseHandler):
    """
    文本 Handler
    
    处理 sentence 事件，发送文本到前端
    """
    
    async def handle(self, event: "OutputEvent") -> None:
        """处理文本事件"""
        text = event.data
        
        if not text or not isinstance(text, str):
            return
        
        # 发送文本到前端
        await self.send({
            "type": "sentence",
            "text": text,
            "seq": event.seq,
        })
        
        logger.debug(f"TextHandler: 发送文本 [{event.seq}] {text[:30]}...")