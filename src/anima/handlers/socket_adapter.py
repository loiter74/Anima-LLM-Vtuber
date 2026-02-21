"""Socket.IO 事件适配器 - 转换后端事件为前端期望的格式"""

from typing import Dict, Any, Callable, Awaitable, Union
from loguru import logger


class SocketEventAdapter:
    """
    Socket.IO 事件适配器

    职责：
    1. 转换后端事件名称为前端期望的名称
    2. 转换事件数据格式（添加缺失字段）
    3. 处理流式文本的完成标记
    """

    # 事件名称映射表
    # sentence 需要映射为 text（前端期望 text 事件）
    EVENT_NAME_MAPPING = {
        "sentence": "text",  # 启用映射：后端发送 sentence，前端期望 text
        "user-transcript": "transcript",
        # 其他事件保持原样
        "audio": "audio",
        "control": "control",
        "tool_call": "tool_call",
        "error": "error",
    }

    def __init__(self, websocket_send: Callable[[str], Awaitable[None]], enable_adapter: bool = True):
        """
        初始化适配器

        Args:
            websocket_send: 原始的 WebSocket 发送函数
            enable_adapter: 是否启用适配（默认 True）
        """
        self._raw_send = websocket_send
        self._enabled = enable_adapter

    async def send(self, message: Union[str, dict]) -> None:
        """
        发送适配后的事件

        Args:
            message: JSON 字符串或字典
        """
        import json

        # 解析消息
        if isinstance(message, str):
            event = json.loads(message)
        else:
            event = message

        # 如果禁用适配器，直接发送
        if not self._enabled:
            await self._raw_send(json.dumps(event) if isinstance(event, dict) else event)
            return

        # 转换事件
        adapted_event = self._adapt_event(event)

        # 发送
        await self._raw_send(json.dumps(adapted_event))

        # 日志
        orig_type = event.get("type", "")
        new_type = adapted_event.get("type", "")
        logger.debug(f"SocketAdapter: {orig_type} -> {new_type}")

    def _adapt_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """转换单个事件"""
        event_type = event.get("type", "")

        # 转换事件名称
        mapped_type = self.EVENT_NAME_MAPPING.get(event_type, event_type)

        # 转换数据格式
        if event_type == "user-transcript":
            return self._adapt_transcript_event(event)
        elif event_type == "sentence":
            # sentence 事件需要特殊处理以保持字段兼容性
            return self._adapt_sentence_event(event)
        else:
            # 其他事件保持原样，只转换 type
            return {"type": mapped_type, **{k: v for k, v in event.items() if k != "type"}}

    def _adapt_sentence_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """转换文本事件"""
        text = event.get("text", "")
        seq = event.get("seq", 0)

        # 检查是否是完成标记（空文本）
        if not text:
            return {
                "type": "text",
                "text": "",
                "seq": seq,  # 保留 seq 字段，前端需要它来判断重复的完成标记
                "from_name": "AI",  # 标记完整消息结束
            }

        # 流式文本片段
        return {
            "type": "text",
            "text": text,
            "seq": seq,  # 保留 seq 字段
            # 不发送 from_name，前端会累积
        }

    def _adapt_transcript_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """转换 ASR 转录事件"""
        return {
            "type": "transcript",
            "text": event.get("text", ""),
            "is_final": True,
        }
