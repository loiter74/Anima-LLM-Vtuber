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

    # 类变量，用于减少日志频率
    _log_counter = 0
    _log_interval = 10  # 每10个片段打印一次日志

    async def handle(self, event: "OutputEvent") -> None:
        """处理文本事件"""
        text = event.data

        # 检查是否是完成标记（空文本）
        is_complete = event.metadata.get("is_complete", False) if event.metadata else False

        if is_complete:
            # 发送完成标记到前端（保留INFO级别，这是重要事件）
            logger.info(f"[TextHandler] ✅ 发送完成标记 [seq={event.seq}]")
            logger.debug(f"[TextHandler] Handler实例ID={id(self)}")
            await self.send({
                "type": "sentence",
                "text": "",  # 空文本表示完成
                "seq": event.seq,
            })
            # 重置计数器
            self._log_counter = 0
            return

        # 普通文本
        if not text or not isinstance(text, str):
            return

        # 发送文本到前端
        self._log_counter += 1

        # 只在特定间隔打印DEBUG日志，减少日志量
        if self._log_counter % self._log_interval == 0:
            logger.debug(f"[TextHandler] 📤 发送文本片段 [seq={event.seq}] (第{self._log_counter}个片段)")
            logger.debug(f"[TextHandler] 片段内容: {text[:50]}...")

        await self.send({
            "type": "sentence",
            "text": text,
            "seq": event.seq,
        })
