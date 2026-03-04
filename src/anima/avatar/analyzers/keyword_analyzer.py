"""
关键词情绪分析器（增强版）

通过关键词匹配推断文本中的情绪。
实现新的 IEmotionAnalyzer 接口，增强错误处理和验证逻辑。
"""

from typing import List, Optional, Dict, Any
from loguru import logger

from .base import IEmotionAnalyzer, EmotionData


class KeywordAnalyzer(IEmotionAnalyzer):
    """
    基于关键词的情绪分析器

    通过关键词匹配推断情绪。
    支持自定义关键词映射和多种置信度计算模式。

    功能:
    - 基于关键词匹配推断情绪
    - 支持多种置信度计算模式
    - 支持自定义关键词映射
    - 可扩展的关键词库
    - 完善的错误处理和验证

    Attributes:
        keywords: 关键词到情绪的映射字典
        confidence_mode: 置信度计算模式

    Example:
        >>> analyzer = KeywordAnalyzer(
        ...     confidence_mode="weighted"
        ... )
        >>> result = analyzer.extract("我今天好开心啊！")
        >>> print(result.primary)
        'happy'
        >>> print(result.confidence)
        0.85
    """

    # 默认关键词映射（扩展版）
    DEFAULT_KEYWORDS = {
        "happy": [
            # 基础词
            "开心", "快乐", "高兴", "喜欢", "爱",
            # 语气词
            "哈哈", "耶", "太好了", "真棒", "棒",
            # 口语
            "爽", "爽快", "开心", "愉快", "欣喜",
            # 成语/高级词
            "喜出望外", "欣喜若狂", "心花怒放", "兴高采烈"
        ],
        "sad": [
            # 基础词
            "难过", "悲伤", "哭", "伤心", "遗憾",
            # 语气词
            "呜呜", "痛苦", "失望",
            # 口语
            "郁闷", "沮丧", "抑郁", "悲伤",
            # 成语/高级词
            "痛不欲生", "心如刀割", "悲痛欲绝"
        ],
        "angry": [
            # 基础词
            "生气", "愤怒", "讨厌", "哼",
            # 口语
            "气死", "烦人", "可恶", "火大",
            # 语气词
            "滚", "滚蛋",
            # 成语/高级词
            "怒不可遏", "怒发冲冠", "暴跳如雷"
        ],
        "surprised": [
            # 基础词
            "哇", "天啊", "真的吗", "不敢相信",
            # 口语
            "震惊", "居然", "竟然",
            # 语气词
            "咦", "哎哟",
            # 成语/高级词
            "大吃一惊", "目瞪口呆", "惊愕"
        ],
        "thinking": [
            # 基础词
            "嗯", "让我想想", "思考", "考虑",
            # 口语
            "分析", "研究", "琢磨", "思索",
            # 语气词
            "嗯嗯", "呃",
            # 高级词
            "沉思", "斟酌", "考量"
        ],
        "neutral": [
            # 基础词
            "还好", "一般", "普通",
            # 口语
            "可以", "行", "好的", "OK",
            # 语气词
            "嗯", "哦", "噢"
        ]
    }

    def __init__(
        self,
        keywords: Optional[Dict[str, List[str]]] = None,
        confidence_mode: str = "weighted"
    ):
        """
        初始化分析器

        Args:
            keywords: 自定义关键词映射。如果为 None，使用默认映射
            confidence_mode: 置信度计算模式
                - "count": 基于关键词数量（0.15 * count，最多 1.0）
                - "weighted": 基于加权得分（关键词数量 / 文本长度 * 10）
                - "normalized": 归一化（最高分情绪得 1.0，其余按比例）
                - "binary": 二值（有匹配=0.5，无匹配=0.0）
        """
        self.keywords = keywords or self.DEFAULT_KEYWORDS.copy()
        self._confidence_mode = confidence_mode

        # 验证 confidence_mode
        if confidence_mode not in ["count", "weighted", "normalized", "binary"]:
            raise ValueError(
                f"无效的 confidence_mode: {confidence_mode}. "
                f"可选值: 'count', 'weighted', 'normalized', 'binary'"
            )

    def extract(self, text: str, context: Optional[Dict[str, Any]] = None) -> EmotionData:
        """
        从文本中提取情绪

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
            # 统计每种情绪的关键词出现次数
            scores = {}
            for emotion, words in self.keywords.items():
                count = sum(1 for word in words if word in text)
                if count > 0:
                    scores[emotion] = count

            # 计算置信度
            confidence = self._calculate_confidence(scores, text)

            # 提取主要情绪
            primary = self._extract_primary(scores)

            # 构建时间轴（关键词分析不提供时间信息）
            timeline = []

            # 统计信息
            metadata = {
                "source": "keyword",
                "scores": scores,
                "matched_keywords": scores.get(primary, 0),
                "confidence_mode": self._confidence_mode,
                "total_matches": sum(scores.values())
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
        scores: Dict[str, int],
        text: str
    ) -> float:
        """
        计算置信度

        Args:
            scores: 情绪得分字典
            text: 原始文本

        Returns:
            float: 置信度 (0.0 - 1.0)
        """
        if not scores:
            return 0.0

        if self._confidence_mode == "binary":
            # 二值：有匹配=0.5，无匹配=0.0
            return 0.5 if scores else 0.0

        elif self._confidence_mode == "count":
            # 基于数量：关键词数量 * 0.15
            max_score = max(scores.values())
            return min(max_score * 0.15, 1.0)

        elif self._confidence_mode == "weighted":
            # 加权：关键词数量 / 文本长度 * 10
            max_score = max(scores.values())
            text_length = len(text) or 1
            return min(max_score / text_length * 10, 1.0)

        elif self._confidence_mode == "normalized":
            # 归一化：最高分情绪得 1.0
            return 1.0

        else:
            return 0.5

    def _extract_primary(self, scores: Dict[str, int]) -> str:
        """
        提取主要情绪

        Args:
            scores: 情绪得分字典

        Returns:
            str: 主要情绪名称
        """
        if scores:
            return max(scores, key=scores.get)
        else:
            return "neutral"

    def _get_default_emotion_data(self, text: str) -> EmotionData:
        """
        获取默认情绪数据（当提取失败时）

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
                "source": "keyword",
                "mode": "default",
                "text_length": len(text)
            }
        )

    @property
    def name(self) -> str:
        """分析器名称"""
        return "keyword_analyzer"

    @property
    def priority(self) -> int:
        """优先级（低于 LLM 标签）"""
        return 10

    def get_supported_emotions(self) -> List[str]:
        """获取支持的情绪列表"""
        return list(self.keywords.keys())

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
        便捷方法：提取匹配的情绪标签列表

        Args:
            text: 待分析文本

        Returns:
            List[str]: 匹配的情绪标签列表
        """
        result = self.extract(text)
        matched_emotions = result.metadata.get("scores", {})
        return list(matched_emotions.keys())

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
            "scores": result.metadata.get("scores", {}),
            "total_matches": result.metadata.get("total_matches", 0),
            "matched_keywords": result.metadata.get("matched_keywords", 0),
            "has_emotions": result.confidence > 0
        }

    def add_keywords(self, emotion: str, keywords: List[str]) -> None:
        """
        动态添加关键词

        Args:
            emotion: 情绪名称
            keywords: 关键词列表
        """
        if emotion not in self.keywords:
            self.keywords[emotion] = []

        self.keywords[emotion].extend(keywords)

    def remove_keywords(self, emotion: str, keywords: List[str]) -> None:
        """
        移除关键词

        Args:
            emotion: 情绪名称
            keywords: 要移除的关键词列表
        """
        if emotion in self.keywords:
            for keyword in keywords:
                if keyword in self.keywords[emotion]:
                    self.keywords[emotion].remove(keyword)
