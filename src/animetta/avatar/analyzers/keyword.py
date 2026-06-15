"""
Keyword emotion analyzer (enhanced version)

Infers emotions from text through keyword matching.
Implements the new IEmotionAnalyzer interface with enhanced error handling and validation logic.
"""

from typing import Any

from loguru import logger

from .base import EmotionData, IEmotionAnalyzer


class KeywordAnalyzer(IEmotionAnalyzer):
    """
    Keyword-based emotion analyzer

    Infers emotions through keyword matching.
    Supports custom keyword mappings and multiple confidence calculation modes.

    Features:
    - Infers emotions based on keyword matching
    - Supports multiple confidence calculation modes
    - Supports custom keyword mappings
    - Extensible keyword library
    - Comprehensive error handling and validation

    Attributes:
        keywords: Dictionary mapping keywords to emotions
        confidence_mode: Confidence calculation mode

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

    # Default keyword mappings (extended version)
    DEFAULT_KEYWORDS = {
        "happy": [
            # Basic words
            "开心", "快乐", "高兴", "喜欢", "爱",
            # Interjections
            "哈哈", "耶", "太好了", "真棒", "棒",
            # Colloquial
            "爽", "爽快", "开心", "愉快", "欣喜",
            # Idioms/Advanced
            "喜出望外", "欣喜若狂", "心花怒放", "兴高采烈"
        ],
        "sad": [
            # Basic words
            "难过", "悲伤", "哭", "伤心", "遗憾",
            # Interjections
            "呜呜", "痛苦", "失望",
            # Colloquial
            "郁闷", "沮丧", "抑郁", "悲伤",
            # Idioms/Advanced
            "痛不欲生", "心如刀割", "悲痛欲绝"
        ],
        "angry": [
            # Basic words
            "生气", "愤怒", "讨厌", "哼",
            # Colloquial
            "气死", "烦人", "可恶", "火大",
            # Interjections
            "滚", "滚蛋",
            # Idioms/Advanced
            "怒不可遏", "怒发冲冠", "暴跳如雷"
        ],
        "surprised": [
            # Basic words
            "哇", "天啊", "真的吗", "不敢相信",
            # Colloquial
            "震惊", "居然", "竟然",
            # Interjections
            "咦", "哎哟",
            # Idioms/Advanced
            "大吃一惊", "目瞪口呆", "惊愕"
        ],
        "thinking": [
            # Basic words
            "嗯", "让我想想", "思考", "考虑",
            # Colloquial
            "分析", "研究", "琢磨", "思索",
            # Interjections
            "嗯嗯", "呃",
            # Advanced
            "沉思", "斟酌", "考量"
        ],
        "neutral": [
            # Basic words
            "还好", "一般", "普通",
            # Colloquial
            "可以", "行", "好的", "OK",
            # Interjections
            "嗯", "哦", "噢"
        ]
    }

    def __init__(
        self,
        keywords: dict[str, list[str]] | None = None,
        confidence_mode: str = "weighted",
        valid_emotions: list[str] | None = None,
    ):
        """
        Initialize the analyzer

        Args:
            keywords: Custom keyword mapping. If None, uses default mapping
            confidence_mode: Confidence calculation mode
                - "count": Based on keyword count (0.15 * count, max 1.0)
                - "weighted": Based on weighted score (keyword count / text length * 10)
                - "normalized": Normalized (highest scored emotion gets 1.0, others proportionally)
                - "binary": Binary (has match=0.5, no match=0.0)
            valid_emotions: Optional list of valid emotions to filter keyword groups.
                If None, uses all default keyword groups.
        """
        self.keywords = keywords or self.DEFAULT_KEYWORDS.copy()
        self._confidence_mode = confidence_mode

        # Validate confidence_mode
        if confidence_mode not in ["count", "weighted", "normalized", "binary"]:
            raise ValueError(
                f"Invalid confidence_mode: {confidence_mode}. "
                f"Valid values: 'count', 'weighted', 'normalized', 'binary'"
            )

    def extract(self, text: str, context: dict[str, Any] | None = None) -> EmotionData:
        """
        Extract emotions from text

        Args:
            text: Text to analyze
            context: Optional context information (not used by this analyzer)

        Returns:
            EmotionData: Extracted emotion data

        Raises:
            ValueError: Text is empty or invalid
        """
        # Input validation
        if not self.validate_input(text):
            raise ValueError(f"Invalid input text: {text}")

        try:
            # Count keyword occurrences for each emotion
            scores = {}
            for emotion, words in self.keywords.items():
                count = sum(1 for word in words if word in text)
                if count > 0:
                    scores[emotion] = count

            # Calculate confidence
            confidence = self._calculate_confidence(scores, text)

            # Extract primary emotion
            primary = self._extract_primary(scores)

            # Build timeline (keyword analysis does not provide time info)
            timeline: list[dict[str, Any]] = []

            # Statistics
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
            logger.error(f"[{self.name}] Failed to extract emotions: {e}")
            # Return default emotion
            return self._get_default_emotion_data(text)

    def _calculate_confidence(
        self,
        scores: dict[str, int],
        text: str
    ) -> float:
        """
        Calculate confidence

        Args:
            scores: Emotion score dictionary
            text: Original text

        Returns:
            float: Confidence (0.0 - 1.0)
        """
        if not scores:
            return 0.0

        if self._confidence_mode == "binary":
            # Binary: has match=0.5, no match=0.0
            return 0.5 if scores else 0.0

        elif self._confidence_mode == "count":
            # Based on count: keyword count * 0.15
            max_score = max(scores.values())
            return min(max_score * 0.15, 1.0)

        elif self._confidence_mode == "weighted":
            # Weighted: keyword count / text length * 10
            max_score = max(scores.values())
            text_length = len(text) or 1
            return min(max_score / text_length * 10, 1.0)

        elif self._confidence_mode == "normalized":
            # Normalized: highest scored emotion gets 1.0
            return 1.0

        else:
            return 0.5

    def _extract_primary(self, scores: dict[str, int]) -> str:
        """
        Extract primary emotion

        Args:
            scores: Emotion score dictionary

        Returns:
            str: Primary emotion name
        """
        if scores:
            return max(scores, key=scores.get)
        else:
            return "neutral"

    def _get_default_emotion_data(self, text: str) -> EmotionData:
        """
        Get default emotion data (when extraction fails)

        Args:
            text: Original text

        Returns:
            EmotionData: Default emotion data
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
        """Analyzer name"""
        return "keyword_analyzer"

    @property
    def priority(self) -> int:
        """Priority (lower than LLM tag)"""
        return 10

    def get_supported_emotions(self) -> list[str]:
        """Get supported emotions list"""
        return list(self.keywords.keys())

    def validate_input(self, text: str) -> bool:
        """
        Validate input parameters

        Args:
            text: Text to validate

        Returns:
            bool: Whether valid
        """
        return isinstance(text, str) and len(text.strip()) > 0

    def extract_emotion_tags(self, text: str) -> list[str]:
        """
        Convenience method: extract list of matched emotion tags

        Args:
            text: Text to analyze

        Returns:
            List[str]: List of matched emotion tags
        """
        result = self.extract(text)
        matched_emotions = result.metadata.get("scores", {})
        return list(matched_emotions.keys())

    def get_emotion_summary(self, text: str) -> dict[str, Any]:
        """
        Get emotion summary information

        Args:
            text: Text to analyze

        Returns:
            Dict: Emotion summary
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

    def add_keywords(self, emotion: str, keywords: list[str]) -> None:
        """
        Dynamically add keywords

        Args:
            emotion: Emotion name
            keywords: List of keywords
        """
        if emotion not in self.keywords:
            self.keywords[emotion] = []

        self.keywords[emotion].extend(keywords)

    def remove_keywords(self, emotion: str, keywords: list[str]) -> None:
        """
        Remove keywords

        Args:
            emotion: Emotion name
            keywords: List of keywords to remove
        """
        if emotion in self.keywords:
            for keyword in keywords:
                if keyword in self.keywords[emotion]:
                    self.keywords[emotion].remove(keyword)
