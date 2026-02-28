"""
LLM 标签情绪分析器（增强版）

从 LLM 生成的文本中提取 [happy], [sad] 等情绪标签。
实现新的 IEmotionAnalyzer 接口，增强错误处理和验证逻辑。
"""

from typing import List, Optional, Dict, Any
import re
from loguru import logger

from .base import IEmotionAnalyzer, EmotionData
from anima.live2d.emotion_extractor import EmotionExtractor, EmotionTag


class LLMTagAnalyzer(IEmotionAnalyzer):
    """
    基于 LLM 标签的情绪分析器

    从 LLM 生成的文本中提取 [happy], [sad] 等标签。
    这是现有的 EmotionExtractor 的增强版包装器。

    功能:
    - 提取 LLM 生成的 [emotion] 标签
    - 验证情绪标签的有效性
    - 计算情绪标签的位置分布
    - 支持自定义情绪列表

    Attributes:
        extractor: EmotionExtractor 实例
        valid_emotions: 有效的情绪列表
        confidence_mode: 置信度计算模式

    Example:
        >>> analyzer = LLMTagAnalyzer(
        ...     valid_emotions=["happy", "sad", "angry"],
        ...     confidence_mode="binary"
        ... )
        >>> result = analyzer.extract("Hello [happy] world!")
        >>> print(result.primary)
        'happy'
        >>> print(result.confidence)
        1.0
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
        self.extractor = EmotionExtractor(valid_emotions=valid_emotions)
        self._valid_emotions = set(valid_emotions) if valid_emotions else None
        self._confidence_mode = confidence_mode

        # 验证 confidence_mode
        if confidence_mode not in ["binary", "frequency", "normalized"]:
            raise ValueError(
                f"无效的 confidence_mode: {confidence_mode}. "
                f"可选值: 'binary', 'frequency', 'normalized'"
            )

    def extract(self, text: str, context: Optional[Dict[str, Any]] = None) -> EmotionData:
        """
        从文本中提取情绪标签

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
            # 使用现有的 EmotionExtractor
            result = self.extractor.extract(text)

            # 计算置信度
            confidence = self._calculate_confidence(result, text)

            # 构建时间轴
            timeline = self._build_timeline(result, text)

            # 提取主要情绪
            primary = self._extract_primary(result)

            # 统计信息
            emotion_counts = self._count_emotions(result)
            metadata = {
                "source": "llm_tag",
                "raw_emotions": [str(e) for e in result.emotions],
                "emotion_counts": emotion_counts,
                "confidence_mode": self._confidence_mode
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

    def _calculate_confidence(
        self,
        result: 'EmotionExtractionResult',
        text: str
    ) -> float:
        """
        计算置信度

        Args:
            result: EmotionExtractionResult 对象
            text: 原始文本

        Returns:
            float: 置信度 (0.0 - 1.0)
        """
        if not result.has_emotions:
            return 0.0

        if self._confidence_mode == "binary":
            # 二值：有情绪=1.0，无情绪=0.0
            return 1.0

        elif self._confidence_mode == "frequency":
            # 基于频率：标签数量 / 文本长度
            emotion_count = len(result.emotions)
            text_length = len(result.cleaned_text) or 1
            return min(emotion_count / 10.0, 1.0)

        elif self._confidence_mode == "normalized":
            # 归一化：基于标签强度
            # 这里简化处理，返回 1.0（有标签就有信心）
            return 1.0

        else:
            return 1.0

    def _build_timeline(
        self,
        result: 'EmotionExtractionResult',
        text: str
    ) -> List[Dict[str, Any]]:
        """
        构建时间轴数据

        Args:
            result: EmotionExtractionResult 对象
            text: 原始文本

        Returns:
            List[Dict]: 时间轴数据
        """
        timeline = []

        for emotion_tag in result.emotions:
            timeline.append({
                "emotion": emotion_tag.emotion,
                "position": emotion_tag.position,
                "char_position": emotion_tag.position
            })

        return timeline

    def _extract_primary(self, result: 'EmotionExtractionResult') -> str:
        """
        提取主要情绪

        策略：选择第一个情绪标签（通常是主要情绪）
        """
        if result.has_emotions:
            return result.emotions[0].emotion
        else:
            return "neutral"

    def _count_emotions(self, result: 'EmotionExtractionResult') -> Dict[str, int]:
        """
        统计每种情绪的出现次数
        """
        counts = {}
        for emotion_tag in result.emotions:
            emotion = emotion_tag.emotion
            counts[emotion] = counts.get(emotion, 0) + 1
        return counts

    def _get_default_emotion_data(self, text: str) -> EmotionData:
        """
        获取默认情绪数据（当没有提取到情绪时）

        Args:
            text: 原始文本

        Returns:
            EmotionData: 默认情绪数据
        """
        return EmotionData(
            primary="neutral",
            confidence=0.0,
            timeline=[],
            metadata={
                "source": "llm_tag",
                "mode": "default",
                "text_length": len(text)
            }
        )

    @property
    def name(self) -> str:
        """分析器名称"""
        return "llm_tag_analyzer"

    @property
    def priority(self) -> int:
        """优先级（最高）"""
        return 1

    def get_supported_emotions(self) -> List[str]:
        """获取支持的情绪列表"""
        if self._valid_emotions:
            return list(self._valid_emotions)
        return []

    def validate_input(self, text: str) -> bool:
        """
        验证输入参数

        Args:
            text: 待验证的文本

        Returns:
            bool: 是否有效
        """
        return isinstance(text, str) and len(text.strip()) > 0

    def extract_emotion_tags(self, text: str) -> List[str]:
        """
        便捷方法：只提取情绪标签列表

        Args:
            text: 待分析文本

        Returns:
            List[str]: 情绪标签列表（仅情绪名称）
        """
        result = self.extract(text)
        # 从 raw_emotions 中提取情绪名称
        raw_tags = result.metadata.get("raw_emotions", [])
        # raw_tags 格式: ["EmotionTag(happy, pos=6)", "EmotionTag(sad, pos=21)"]
        # 提取括号内的情绪名称
        import re
        emotions = []
        for tag_str in raw_tags:
            match = re.search(r'EmotionTag\((\w+),', tag_str)
            if match:
                emotions.append(match.group(1))
        return emotions

    def get_emotion_summary(self, text: str) -> Dict[str, Any]:
        """
        获取情绪摘要信息

        Args:
            text: 待分析文本

        Returns:
            Dict: 情绪摘要
        """
        result = self.extract(text)

        return {
            "primary": result.primary,
            "confidence": result.confidence,
            "emotion_counts": result.metadata.get("emotion_counts", {}),
            "timeline_items": len(result.timeline),
            "has_emotions": result.confidence > 0
        }
