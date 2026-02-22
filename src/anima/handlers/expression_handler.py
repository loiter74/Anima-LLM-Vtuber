"""
Live2D 表情 Handler
处理 Live2D 角色表情事件
"""

from anima.handlers.base_handler import BaseHandler
from anima.core import OutputEvent
from loguru import logger


class ExpressionHandler(BaseHandler):
    """
    Live2D 表情 Handler

    处理 Live2D 角色表情事件，通过 WebSocket 发送表情命令到前端

    表情映射:
    - idle: 空闲状态
    - listening: 监听状态
    - thinking: 思考状态
    - speaking: 说话状态
    - surprised: 惊讶状态
    - sad: 悲伤状态
    """

    async def handle(self, event: OutputEvent) -> None:
        """
        处理表情事件

        Args:
            event: 输出事件，data 为表情名称（字符串）
        """
        expression = event.data
        timestamp = event.metadata.get("timestamp")

        logger.info(f"[{self.name}] 🎭 发送表情: {expression}")

        await self.send({
            "type": "expression",
            "expression": expression,
            "timestamp": timestamp
        })

        logger.info(f"[{self.name}] ✅ 表情已发送: {expression}")
