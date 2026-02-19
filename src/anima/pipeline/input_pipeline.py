"""
输入管线
处理用户输入（文本/音频）-> 转换为 Agent 可处理的文本
"""

from typing import TYPE_CHECKING, Dict, Any, Union, List
import numpy as np
from loguru import logger

from .base import BasePipeline, PipelineStepError

if TYPE_CHECKING:
    from anima.core import PipelineContext
    from anima.eventbus import EventBus


class InputPipeline(BasePipeline):
    """
    输入管线
    
    处理用户输入的流程：
    1. ASR（如果是音频）
    2. 文本清洗
    3. 其他预处理
    
    使用示例:
        pipeline = InputPipeline()
        pipeline.add_step(ASRStep(asr_engine))
        pipeline.add_step(TextCleanStep())
        
        ctx = await pipeline.execute(
            raw_input="你好",
            metadata={},
        )
    """
    
    def __init__(self, event_bus: "EventBus" = None):
        """
        初始化输入管线
        
        Args:
            event_bus: 事件总线（可选，用于发送事件）
        """
        super().__init__()
        self.event_bus = event_bus
    
    async def execute(
        self,
        raw_input: Union[str, np.ndarray],
        metadata: Dict[str, Any] = None,
        images: List[Dict[str, Any]] = None,
        from_name: str = "User",
    ) -> "PipelineContext":
        """
        执行输入管线
        
        Args:
            raw_input: 原始输入（文本或音频）
            metadata: 元数据
            images: 图片列表
            from_name: 发送者名称
            
        Returns:
            PipelineContext: 处理后的上下文
        """
        from anima.core import PipelineContext
        
        # 创建上下文
        ctx = PipelineContext(
            raw_input=raw_input,
            metadata=metadata or {},
            images=images,
            from_name=from_name,
        )
        
        # 如果是文本输入，直接设置 text
        if ctx.is_text_input():
            ctx.text = raw_input
            logger.debug(f"文本输入: {raw_input[:50]}...")
        
        # 执行所有步骤
        for step in self._steps:
            try:
                await step(ctx)
            except PipelineStepError as e:
                logger.error(f"输入管线步骤错误: {e}")
                # 记录错误但继续（某些步骤失败不影响整体）
                if e.cause:
                    raise
        
        return ctx
    
    def set_event_bus(self, event_bus: "EventBus") -> None:
        """设置事件总线"""
        self.event_bus = event_bus