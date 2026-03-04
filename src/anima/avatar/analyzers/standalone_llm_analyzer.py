"""
独立的 LLM 标签情绪分析器
不依赖 legacy EmotionExtractor 的完全实现
"""

import re
from typing import List, Optional, Dict, Any
from loguru import logger

from .base import IEmotionAnalyzer, EmotionData


class EmotionTag:
    """表情标签（独立实现）"""
    def __init__(self, emotion: str, position: int, duration: float = 0.0):
        self.emotion = emotion
        self.position = position
        self.duration = duration

    def __repr__(self) -> str:
        return f"EmotionTag({self.emotion}, pos={self.position})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, EmotionTag):
            return False
        return self.emotion == other.emotion and self.position == other.position


class EmotionExtractionResult:
    """表情提取结果（独立实现）"""
    def __init__(self, cleaned_text: str, emotions: List[EmotionTag], has_emotions: bool):
        self.cleaned_text = cleaned_text
        self.emotions = emotions
        self.has_emotions = has_emotions

    def __repr__(self) -> str:
        return f"EmotionExtractionResult(emotions={len(self.emotions)}, cleaned_len={len(self.cleaned_text)})"


class StandaloneLLMTagAnalyzer(IEmotionAnalyzer):
    """
    独立的 LLM 标签情绪分析器

    从 LLM 生成的文本中提取 [happy], [sad] 等情绪标签。
    完全独立实现，不依赖 legacy EmotionExtractor。

    功能:
    - 提取 LLM 生成的 [emotion] 标签
    - 验证情绪标签的有效性
    - 返回清理后的文本
    - 支持自定义情绪列表

    Attributes:
        valid_emotions: 有效的情绪集合
        confidence_mode: 置信度计算模式

    Example:
        >>> analyzer = StandaloneLLMTagAnalyzer(
        ...     valid_emotions=["happy", "sad", "angry"]
        ... )
        >>> result = analyzer.extract("Hello [happy] world!")
        >>> print(result.cleaned_text)
        'Hello  world!'
        >>> print(result.emotions)
        [EmotionTag(happy, pos=6)]
    """

    # 情绪标签的正则模式
    EMOTION_PATTERN = re.compile(r'\[([a-zA-Z_]+)\]')

    def __init__(
        self,
        valid_emotions: Optional[List[str]] = None,
        confidence_mode: str = "binary"
    ):
        """
        初始化分析器

        Args:
            valid_emotions: 有效的情绪列表。如果为 None，则接受所有标签
            confidence_mode: 置信度计算模式
                - "binary": 二值（有标签=1.0，无标签=0.0）
                - "frequency": 基于标签频率（0.5 - 1.0）
                - "normalized": 归一化（0.0 - 1.0）
        """
        self.valid_emotions = set(valid_emotions) if valid_emotions else None
        self._confidence_mode = confidence_mode

        # 验证 confidence_mode
        if confidence_mode not in ["binary", "frequency", "normalized"]:
            raise ValueError(
                f"无效的 confidence_mode: {confidence_mode}. "
                f"可选值: 'binary', 'frequency', 'normalized'"
            )

    def extract_legacy(self, text: str) -> EmotionExtractionResult:
        """
        提取情绪标签（legacy 格式）

        返回 EmotionExtractionResult，包含 cleaned_text 和 EmotionTag 列表。

        Args:
            text: 待分析文本

        Returns:
            EmotionExtractionResult: 清理后的文本和提取的情绪标签
        """
        if not text:
            return EmotionExtractionResult(
                cleaned_text="",
                emotions=[],
                has_emotions=False
            )

        emotions = []
        segments_to_remove = []

        for match in self.EMOTION_PATTERN.finditer(text):
            emotion = match.group(1).lower()
            position = match.start()

            # 如果设置了有效表情列表，则验证
            if self.valid_emotions and emotion not in self.valid_emotions:
                logger.debug(f"[StandaloneLLMTagAnalyzer] 忽略无效表情: [{emotion}]")
                continue

            # 创建表情标签
            emotions.append(EmotionTag(emotion=emotion, position=position))
            segments_to_remove.append((match.start(), match.end()))

        # 清理文本：移除所有表情标签
        cleaned_text = self._remove_segments(text, segments_to_remove)

        logger.debug(f"[StandaloneLLMTagAnalyzer] 提取了 {len(emotions)} 个表情: {emotions}")

        return EmotionExtractionResult(
            cleaned_text=cleaned_text,
            emotions=emotions,
            has_emotions=len(emotions) > 0
        )

    def extract(self, text: str, context: Optional[Dict[str, Any]] = None) -> EmotionData:
        """
        从文本中提取情绪标签（新接口格式）

        Args:
            text: 待分析文本
            context: 可选的上下文信息（本分析器不使用）

        Returns:
            EmotionData: 提取的情绪数据

        Raises:
            ValueError: 文本为空或无效
        """
        # 输入验证
        if not self.validate_input(text):
            raise ValueError(f"输入文本无效: {text}")

        try:
            # 使用 legacy 格式提取
            result = self.extract_legacy(text)

            # 计算置信度
            confidence = self._calculate_confidence(result, text)

            # 构建时间轴
            timeline = self._build_timeline(result)

            # 提取主要情绪
            primary = self._extract_primary(result)

            # 统计信息
            emotion_counts = self._count_emotions(result)
            metadata = {
                "source": "llm_tag",
                "raw_emotions": [str(e) for e in result.emotions],
                "emotion_counts": emotion_counts,
                "confidence_mode": self._confidence_mode,
                "cleaned_text": result.cleaned_text,  # 包含清理后的文本
                "has_emotions": result.has_emotions
            }

            return EmotionData(
                primary=primary,
                confidence=confidence,
                timeline=timeline,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"[{self.name}] 提取情绪失败: {e}")
            # 返回默认情绪
            return self._get_default_emotion_data(text)

    def _remove_segments(self, text: str, segments: List[tuple]) -> str:
        """
        从文本中移除指定片段

        Args:
            text: 原始文本
            segments: 要移除的 (start, end) 位置列表

        Returns:
            清理后的文本
        """
        if not segments:
            return text

        # 按位置排序并从后往前移除（避免位置偏移）
        segments = sorted(segments, key=lambda x: x[0], reverse=True)

        result = text
        for start, end in segments:
            result = result[:start] + result[end:]

        return result

    def _calculate_confidence(self, result: EmotionExtractionResult, text: str) -> float:
        """计算置信度"""
        if not result.has_emotions:
            return 0.0

        if self._confidence_mode == "binary":
            return 1.0
        elif self._confidence_mode == "frequency":
            emotion_count = len(result.emotions)
            text_length = len(result.cleaned_text) or 1
            return min(emotion_count / 10.0, 1.0)
        elif self._confidence_mode == "normalized":
            return 1.0
        else:
            return 1.0

    def _build_timeline(self, result: EmotionExtractionResult) -> List[Dict[str, Any]]:
        """构建时间轴数据"""
        timeline = []
        for emotion_tag in result.emotions:
            timeline.append({
                "emotion": emotion_tag.emotion,
                "position": emotion_tag.position,
                "char_position": emotion_tag.position
            })
        return timeline

    def _extract_primary(self, result: EmotionExtractionResult) -> str:
        """提取主要情绪"""
        if result.has_emotions:
            return result.emotions[0].emotion
        else:
            return "neutral"

    def _count_emotions(self, result: EmotionExtractionResult) -> Dict[str, int]:
        """统计每种情绪的出现次数"""
        counts = {}
        for emotion_tag in result.emotions:
            emotion = emotion_tag.emotion
            counts[emotion] = counts.get(emotion, 0) + 1
        return counts

    def _get_default_emotion_data(self, text: str) -> EmotionData:
        """获取默认情绪数据（当没有提取到情绪时）"""
        return EmotionData(
            primary="neutral",
            confidence=0.0,
            timeline=[],
            metadata={
                "source": "llm_tag",
                "mode": "default",
                "text_length": len(text),
                "cleaned_text": text,
                "has_emotions": False
            }
        )

    @property
    def name(self) -> str:
        """分析器名称"""
        return "standalone_llm_tag_analyzer"

    @property
    def priority(self) -> int:
        """优先级（最高）"""
        return 1

    def get_supported_emotions(self) -> List[str]:
        """获取支持的情绪列表"""
        if self.valid_emotions:
            return list(self.valid_emotions)
        return []

    def validate_input(self, text: str) -> bool:
        """验证输入参数"""
        return isinstance(text, str) and len(text.strip()) > 0
