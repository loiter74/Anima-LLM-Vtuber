"""
表情提取 Pipeline 步骤
从 LLM 响应中提取表情标签，并清理文本
"""

from typing import List, Optional
from loguru import logger

from ..base import PipelineStep
from anima.live2d.analyzers.standalone_llm_analyzer import (
    StandaloneLLMTagAnalyzer,
    EmotionTag,
    EmotionExtractionResult
)


class EmotionExtractionStep(PipelineStep):
    """
    表情提取步骤

    在 OutputPipeline 之后、TTS 之前执行
    从 LLM 响应文本中提取表情标签，并清理文本用于 TTS

    功能：
    1. 从 response 中提取表情标签（如 [happy]）
    2. 更新 response 为清理后的文本（不含表情标签）
    3. 将提取的表情标签存储到 metadata["emotions"]

    示例:
        输入: ctx.response = "Hello [happy] world!"
        输出:
            ctx.response = "Hello  world!"
            ctx.metadata["emotions"] = [EmotionTag("happy", 6)]
    """

    def __init__(
        self,
        valid_emotions: Optional[List[str]] = None,
        enabled: bool = True
    ):
        """
        初始化表情提取步骤

        Args:
            valid_emotions: 有效的表情列表。如果为 None，则接受所有标签
            enabled: 是否启用
        """
        self._valid_emotions = valid_emotions
        self._enabled = enabled
        # 使用新的独立分析器（不依赖 legacy EmotionExtractor）
        self.extractor = StandaloneLLMTagAnalyzer(valid_emotions=valid_emotions)

    @property
    def name(self) -> str:
        return "emotion_extraction"

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def process(self, ctx) -> None:
        """
        处理上下文，提取表情标签

        Args:
            ctx: PipelineContext 对象
        """
        # 检查是否有响应文本
        if not ctx.response:
            logger.debug("[EmotionExtractionStep] 响应为空，跳过")
            return

        original_text = ctx.response

        # 提取表情标签
        result = self.extractor.extract(original_text)

        # 更新上下文
        ctx.response = result.cleaned_text
        ctx.metadata["emotions"] = result.emotions
        ctx.metadata["has_emotions"] = result.has_emotions

        if result.has_emotions:
            logger.info(
                f"[EmotionExtractionStep] 提取了 {len(result.emotions)} 个表情: "
                f"{[e.emotion for e in result.emotions]}"
            )
            logger.debug(f"[EmotionExtractionStep] 原始文本: {original_text[:100]}...")
            logger.debug(f"[EmotionExtractionStep] 清理文本: {result.cleaned_text[:100]}...")
        else:
            logger.debug("[EmotionExtractionStep] 未检测到表情标签")
