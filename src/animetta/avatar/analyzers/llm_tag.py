"""
Standalone LLM tag emotion analyzer
A complete implementation independent of the legacy EmotionExtractor
"""

import re
from typing import Any

from loguru import logger

from .base import EmotionData, IEmotionAnalyzer


class EmotionTag:
    """Emotion tag (standalone implementation)"""
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
    """Emotion extraction result (standalone implementation)"""
    def __init__(self, cleaned_text: str, emotions: list[EmotionTag], has_emotions: bool):
        self.cleaned_text = cleaned_text
        self.emotions = emotions
        self.has_emotions = has_emotions

    def __repr__(self) -> str:
        return f"EmotionExtractionResult(emotions={len(self.emotions)}, cleaned_len={len(self.cleaned_text)})"


class StandaloneLLMTagAnalyzer(IEmotionAnalyzer):
    """
    Standalone LLM tag emotion analyzer

    Extracts emotion tags like [happy], [sad] from LLM-generated text.
    Fully independent implementation, no dependency on legacy EmotionExtractor.

    Features:
    - Extracts LLM-generated [emotion] tags
    - Validates emotion tag validity
    - Returns cleaned text
    - Supports custom emotion lists

    Attributes:
        valid_emotions: Set of valid emotions
        confidence_mode: Confidence calculation mode

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

    # Regex pattern for emotion tags
    EMOTION_PATTERN = re.compile(r'\[([a-zA-Z_]+)\]')

    def __init__(
        self,
        valid_emotions: list[str] | None = None,
        confidence_mode: str = "binary"
    ):
        """
        Initialize the analyzer

        Args:
            valid_emotions: List of valid emotions. If None, accept all tags
            confidence_mode: Confidence calculation mode
                - "binary": Binary (has tag=1.0, no tag=0.0)
                - "frequency": Based on tag frequency (0.5 - 1.0)
                - "normalized": Normalized (0.0 - 1.0)
        """
        self.valid_emotions = set(valid_emotions) if valid_emotions else None
        self._confidence_mode = confidence_mode

        # Validate confidence_mode
        if confidence_mode not in ["binary", "frequency", "normalized"]:
            raise ValueError(
                f"Invalid confidence_mode: {confidence_mode}. "
                f"Valid values: 'binary', 'frequency', 'normalized'"
            )

    def extract_legacy(self, text: str) -> EmotionExtractionResult:
        """
        Extract emotion tags (legacy format)

        Returns EmotionExtractionResult containing cleaned_text and EmotionTag list.

        Args:
            text: Text to analyze

        Returns:
            EmotionExtractionResult: Cleaned text and extracted emotion tags
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

            # If valid emotions are set, validate
            if self.valid_emotions and emotion not in self.valid_emotions:
                logger.debug(f"[StandaloneLLMTagAnalyzer] Ignoring invalid emotion: [{emotion}]")
                continue

            # Create emotion tag
            emotions.append(EmotionTag(emotion=emotion, position=position))
            segments_to_remove.append((match.start(), match.end()))

        # Clean text: remove all emotion tags
        cleaned_text = self._remove_segments(text, segments_to_remove)

        logger.debug(f"[StandaloneLLMTagAnalyzer] Extracted {len(emotions)} emotions: {emotions}")

        return EmotionExtractionResult(
            cleaned_text=cleaned_text,
            emotions=emotions,
            has_emotions=len(emotions) > 0
        )

    def extract(self, text: str, context: dict[str, Any] | None = None) -> EmotionData:
        """
        Extract emotion tags from text (new interface format)

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
            # Use legacy format extraction
            result = self.extract_legacy(text)

            # Calculate confidence
            confidence = self._calculate_confidence(result, text)

            # Build timeline
            timeline = self._build_timeline(result)

            # Extract primary emotion
            primary = self._extract_primary(result)

            # Statistics
            emotion_counts = self._count_emotions(result)
            metadata = {
                "source": "llm_tag",
                "raw_emotions": [str(e) for e in result.emotions],
                "emotion_counts": emotion_counts,
                "confidence_mode": self._confidence_mode,
                "cleaned_text": result.cleaned_text,  # Contains cleaned text
                "has_emotions": result.has_emotions
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

    def _remove_segments(self, text: str, segments: list[tuple]) -> str:
        """
        Remove specified segments from text

        Args:
            text: Original text
            segments: List of (start, end) positions to remove

        Returns:
            Cleaned text
        """
        if not segments:
            return text

        # Sort by position and remove from back to front (avoid offset issues)
        segments = sorted(segments, key=lambda x: x[0], reverse=True)

        result = text
        for start, end in segments:
            result = result[:start] + result[end:]

        return result

    def _calculate_confidence(self, result: EmotionExtractionResult, text: str) -> float:
        """Calculate confidence"""
        if not result.has_emotions:
            return 0.0

        if self._confidence_mode == "binary":
            return 1.0
        elif self._confidence_mode == "frequency":
            emotion_count = len(result.emotions)
            len(result.cleaned_text) or 1
            return min(emotion_count / 10.0, 1.0)
        elif self._confidence_mode == "normalized":
            return 1.0
        else:
            return 1.0

    def _build_timeline(self, result: EmotionExtractionResult) -> list[dict[str, Any]]:
        """Build timeline data"""
        timeline = []
        for emotion_tag in result.emotions:
            timeline.append({
                "emotion": emotion_tag.emotion,
                "position": emotion_tag.position,
                "char_position": emotion_tag.position
            })
        return timeline

    def _extract_primary(self, result: EmotionExtractionResult) -> str:
        """Extract primary emotion"""
        if result.has_emotions:
            return result.emotions[0].emotion
        else:
            return "neutral"

    def _count_emotions(self, result: EmotionExtractionResult) -> dict[str, int]:
        """Count occurrences of each emotion"""
        counts: dict[str, int] = {}
        for emotion_tag in result.emotions:
            emotion = emotion_tag.emotion
            counts[emotion] = counts.get(emotion, 0) + 1
        return counts

    def _get_default_emotion_data(self, text: str) -> EmotionData:
        """Get default emotion data (when no emotion is extracted)"""
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
        """Analyzer name"""
        return "standalone_llm_tag_analyzer"

    @property
    def priority(self) -> int:
        """Priority (highest)"""
        return 1

    def get_supported_emotions(self) -> list[str]:
        """Get supported emotions list"""
        if self.valid_emotions:
            return list(self.valid_emotions)
        return []

    def validate_input(self, text: str) -> bool:
        """Validate input parameters"""
        return isinstance(text, str) and len(text.strip()) > 0
