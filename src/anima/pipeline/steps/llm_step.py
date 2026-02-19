"""
Agent 步骤 - 调用 AI Agent 生成响应
"""

from typing import TYPE_CHECKING, AsyncIterator
from loguru import logger

from ..base import PipelineStep, PipelineStepError
from anima.core import EventType

if TYPE_CHECKING:
    from anima.core import PipelineContext
    from anima.services.agent import AgentInterface
    from anima.eventbus import EventBus


class LLMStep(PipelineStep):
    """
    LLM/Agent 步骤
    
    调用 AI Agent 生成响应，并通过 EventBus 发送事件
    """
    
    def __init__(
        self,
        agent: "AgentInterface",
        event_bus: "EventBus",
    ):
        """
        初始化 Agent 步骤
        
        Args:
            agent: Agent 实例
            event_bus: 事件总线（用于发送响应事件）
        """
        self.agent = agent
        self.event_bus = event_bus
        self._seq = 0
    
    async def process(self, ctx: "PipelineContext") -> None:
        """处理输入，调用 Agent"""
        if not ctx.text:
            ctx.set_error(self.name, "没有有效的输入文本")
            return
        
        if self.agent is None:
            ctx.set_error(self.name, "Agent 未初始化")
            return
        
        self._seq = 0
        full_response = ""
        
        try:
            # 调用 Agent 生成响应（流式）
            agent_stream = self.agent.chat(
                text=ctx.text,
                images=ctx.images,
            )
            
            async for chunk in agent_stream:
                # 检查是否被打断
                if ctx.skip_remaining:
                    logger.info("Agent 步骤被打断")
                    break
                
                # 处理不同类型的 chunk
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type", "text")
                    chunk_data = chunk.get("content", chunk.get("data", ""))
                    
                    if chunk_type == "text":
                        await self._emit_event(EventType.SENTENCE, chunk_data)
                        full_response += chunk_data
                        
                    elif chunk_type == "sentence":
                        await self._emit_event(EventType.SENTENCE, chunk_data)
                        full_response += chunk_data
                        
                    elif chunk_type == "tool_call":
                        await self._emit_event(EventType.TOOL_CALL, chunk)
                        
                elif isinstance(chunk, str):
                    await self._emit_event(EventType.SENTENCE, chunk)
                    full_response += chunk
            
            # 更新上下文
            ctx.response = full_response
            logger.debug(f"Agent 响应完成: {len(full_response)} 字符")
            
        except Exception as e:
            logger.error(f"Agent 处理出错: {e}")
            ctx.set_error(self.name, f"Agent 处理失败: {str(e)}")
            raise PipelineStepError(self.name, str(e), e)
    
    async def _emit_event(self, event_type: str, data) -> None:
        """发射事件到 EventBus"""
        from anima.core import OutputEvent
        
        if self.event_bus is None:
            return
        
        self._seq += 1
        
        event = OutputEvent(
            type=event_type,
            data=data,
            seq=self._seq,
        )
        
        await self.event_bus.emit(event)