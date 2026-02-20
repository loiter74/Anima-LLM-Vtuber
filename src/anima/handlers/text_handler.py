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

        # 检查是否是完成标记（空文本）
        is_complete = event.metadata.get("is_complete", False) if event.metadata else False

        if is_complete:
            # 发送完成标记到前端
            logger.info(f"TextHandler: 发送完成标记 [seq={event.seq}]")
            logger.debug(f"TextHandler: Handler实例ID={id(self)}")
            await self.send({
                "type": "sentence",
                "text": "",  # 空文本表示完成
                "seq": event.seq,
            })
            logger.info(f"TextHandler: 完成标记已发送 [seq={event.seq}]")
            return

        # 普通文本
        if not text or not isinstance(text, str):
            return

        # 发送文本到前端
        logger.info(f"TextHandler: 发送文本片段 [seq={event.seq}] text={text[:50]}...")
        logger.debug(f"TextHandler: Handler实例ID={id(self)}")
        await self.send({
            "type": "sentence",
            "text": text,
            "seq": event.seq,
        })

        logger.info(f"TextHandler: 文本已发送 [seq={event.seq}]")
