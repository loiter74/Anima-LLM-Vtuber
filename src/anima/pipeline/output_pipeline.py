"""
输出管线
处理 Agent 响应 -> 分发到各个 Handler
"""

from typing import TYPE_CHECKING, AsyncIterator, Any, Dict
from loguru import logger

from .base import BasePipeline, PipelineStepError
from anima.core import OutputEvent, EventType

if TYPE_CHECKING:
    from anima.core import PipelineContext
    from anima.eventbus import EventBus


class OutputPipeline(BasePipeline):
    """
    输出管线
    
    处理 Agent 响应的流程：
    1. 收集 Agent 输出
    2. 通过 EventBus 分发事件
    3. 各 Handler 处理事件
    
    使用示例:
        pipeline = OutputPipeline(event_bus)
        
        async for event in pipeline.process_agent_response(agent_response):
            # event 是 OutputEvent
            pass
    """
    
    def __init__(self, event_bus: "EventBus" = None):
        """
        初始化输出管线
        
        Args:
            event_bus: 事件总线
        """
        super().__init__()
        self.event_bus = event_bus
        self._seq = 0
        self._interrupted = False
    
    async def process(
        self,
        ctx: "PipelineContext",
        agent_stream: AsyncIterator,
    ) -> str:
        """
        处理 Agent 响应流
        
        Args:
            ctx: 管线上下文
            agent_stream: Agent 的异步响应流
            
        Returns:
            str: 完整的响应文本
        """
        full_response = ""
        self._seq = 0
        self._interrupted = False
        
        try:
            async for chunk in agent_stream:
                if self._interrupted or ctx.skip_remaining:
                    logger.info("输出管线被中断")
                    break

                # 处理不同类型的 chunk
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type", "text")
                    chunk_data = chunk.get("content", chunk.get("data", ""))

                    if chunk_type == "text":
                        await self._emit_sentence(chunk_data)
                        full_response += chunk_data

                    elif chunk_type == "sentence":
                        await self._emit_sentence(chunk_data)
                        full_response += chunk_data

                    elif chunk_type == "tool_call":
                        await self._emit_event(EventType.TOOL_CALL, chunk)

                elif isinstance(chunk, str):
                    await self._emit_sentence(chunk)
                    full_response += chunk

            # 发送完成标记（只要没被中断就发送，即使内容为空）
            if not self._interrupted:
                await self._emit_completion_marker()

            # 更新上下文
            ctx.response = full_response
            return full_response
            
        except Exception as e:
            logger.error(f"输出管线处理出错: {e}")
            raise
    
    async def _emit_sentence(self, text: str) -> None:
        """发射句子事件"""
        if not text or not text.strip():
            return

        await self._emit_event(EventType.SENTENCE, text)

    async def _emit_completion_marker(self) -> None:
        """发送文本完成标记"""
        if self.event_bus is None:
            return

        from anima.core import OutputEvent

        # 发送空文本作为完成标记
        event = OutputEvent(
            type=EventType.SENTENCE,
            data="",  # 空文本表示完成
            seq=self._seq + 1,
            metadata={"is_complete": True},
        )

        await self.event_bus.emit(event)
        logger.debug("输出管线: 发送完成标记")

    async def _emit_event(self, event_type: str, data: Any) -> None:
        """发射事件到 EventBus"""
        if self.event_bus is None:
            return
        
        self._seq += 1
        
        event = OutputEvent(
            type=event_type,
            data=data,
            seq=self._seq,
        )
        
        await self.event_bus.emit(event)
    
    def interrupt(self) -> None:
        """中断输出管线"""
        self._interrupted = True
        logger.info("输出管线已标记中断")
    
    def reset(self) -> None:
        """重置输出管线"""
        self._seq = 0
        self._interrupted = False
    
    def set_event_bus(self, event_bus: "EventBus") -> None:
        """设置事件总线"""
        self.event_bus = event_bus