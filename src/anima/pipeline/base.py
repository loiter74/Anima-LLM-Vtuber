"""
管线步骤抽象基类
基于责任链模式的处理管线
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional
from loguru import logger

if TYPE_CHECKING:
    from anima.core import PipelineContext


class PipelineStepError(Exception):
    """管线步骤错误"""
    
    def __init__(self, step_name: str, message: str, cause: Exception = None):
        self.step_name = step_name
        self.message = message
        self.cause = cause
        super().__init__(f"[{step_name}] {message}")


class PipelineStep(ABC):
    """
    管线步骤抽象基类
    
    每个步骤负责处理数据的一个方面
    步骤可以修改上下文、添加信息或中断处理
    
    使用示例:
        class ASRStep(PipelineStep):
            @property
            def name(self) -> str:
                return "asr"
            
            async def process(self, ctx: PipelineContext) -> None:
                if ctx.is_audio_input():
                    ctx.text = await self.asr.transcribe(ctx.raw_input)
    """
    
    @property
    def name(self) -> str:
        """步骤名称（用于日志和调试）"""
        return self.__class__.__name__.replace("Step", "").lower()
    
    @property
    def enabled(self) -> bool:
        """是否启用"""
        return True
    
    @abstractmethod
    async def process(self, ctx: "PipelineContext") -> None:
        """
        处理管线上下文
        
        Args:
            ctx: 管线上下文对象（会被原地修改）
            
        Raises:
            PipelineStepError: 处理出错时抛出
        """
        pass
    
    async def __call__(self, ctx: "PipelineContext") -> "PipelineContext":
        """
        使步骤可调用
        
        Args:
            ctx: 管线上下文对象
            
        Returns:
            PipelineContext: 处理后的上下文
        """
        if not self.enabled:
            logger.debug(f"步骤 {self.name} 已禁用，跳过")
            return ctx
        
        if ctx.skip_remaining:
            logger.debug(f"步骤 {self.name} 被跳过（skip_remaining=True）")
            return ctx
        
        try:
            logger.debug(f"执行步骤: {self.name}")
            await self.process(ctx)
            return ctx
        except PipelineStepError:
            raise
        except Exception as e:
            logger.error(f"步骤 {self.name} 执行出错: {e}")
            ctx.set_error(self.name, str(e))
            raise PipelineStepError(self.name, str(e), e)


class BasePipeline:
    """
    管线基类
    
    管理一系列 PipelineStep 的执行
    """
    
    def __init__(self):
        self._steps: List[PipelineStep] = []
    
    def add_step(self, step: PipelineStep) -> "BasePipeline":
        """
        添加步骤
        
        Args:
            step: PipelineStep 实例
            
        Returns:
            self（支持链式调用）
        """
        self._steps.append(step)
        logger.debug(f"添加管线步骤: {step.name}")
        return self
    
    def remove_step(self, step_name: str) -> bool:
        """
        移除步骤
        
        Args:
            step_name: 步骤名称
            
        Returns:
            bool: 是否成功移除
        """
        for i, step in enumerate(self._steps):
            if step.name == step_name:
                self._steps.pop(i)
                logger.debug(f"移除管线步骤: {step_name}")
                return True
        return False
    
    def get_step(self, step_name: str) -> Optional[PipelineStep]:
        """
        获取步骤
        
        Args:
            step_name: 步骤名称
            
        Returns:
            PipelineStep 或 None
        """
        for step in self._steps:
            if step.name == step_name:
                return step
        return None
    
    def clear_steps(self) -> None:
        """清空所有步骤"""
        self._steps.clear()
        logger.debug("已清空所有管线步骤")
    
    @property
    def step_names(self) -> List[str]:
        """获取所有步骤名称"""
        return [step.name for step in self._steps]