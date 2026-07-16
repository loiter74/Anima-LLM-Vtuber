"""
Emotion Analyzer Interface and Basic Data Structures

Defines the interface that all emotion analyzers must implement.
Uses the strategy pattern and plugin architecture for dynamic extensibility.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmotionData:
    """
    Emotion Data (unified format)

    All emotion analyzers must return this format.
    Contains emotion information, confidence, timeline, and metadata.

    Attributes:
        primary: Primary emotion (e.g., "happy", "sad")
        confidence: Confidence score (0.0 - 1.0)
        timeline: List of emotion timeline segments
        metadata: Additional info (for debugging and extension)

    Example:
        >>> data = EmotionData(
        ...     primary="happy",
        ...     confidence=0.9,
        ...     timeline=[{"emotion": "happy", "position": 6}],
        ...     metadata={"source": "llm_tag"}
        ... )
        >>> data.to_dict()
        {
            'primary': 'happy',
            'confidence': 0.9,
            'timeline': [{'emotion': 'happy', 'position': 6}],
            'metadata': {'source': 'llm_tag'}
        }
    """

    primary: str
    confidence: float
    timeline: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary (for serialization and logging)

        Returns:
            Dict[str, Any]: Dictionary containing all fields
        """
        return {
            "primary": self.primary,
            "confidence": self.confidence,
            "timeline": self.timeline,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        """String representation"""
        return (
            f"EmotionData(primary={self.primary}, "
            f"confidence={self.confidence:.2f}, "
            f"timeline_items={len(self.timeline)})"
        )


class IEmotionAnalyzer(ABC):
    """
    Emotion Analyzer Interface

    All emotion analyzers must implement this interface.
    The plugin system achieves polymorphism through this interface.

    Design Patterns:
    - Strategy Pattern: Different emotion analysis strategies
    - Plugin Pattern: Dynamically registerable analyzers

    Usage Examples:
        >>> from anima.avatar.analyzers import LLMTagAnalyzer
        >>> analyzer = LLMTagAnalyzer(valid_emotions=["happy", "sad"])
        >>> result = analyzer.extract("Hello [happy] world!")
        >>> print(result.primary)
        'happy'

    Extension Example:
        >>> from anima.avatar.analyzers.base import IEmotionAnalyzer
        >>> class MyAnalyzer(IEmotionAnalyzer):
        ...     def extract(self, text, context=None):
        ...         # Custom analysis logic
        ...         return EmotionData(primary="neutral", confidence=0.5)
        ...
        >>> from anima.avatar.factory import EmotionAnalyzerFactory
        >>> EmotionAnalyzerFactory.register("my_analyzer", MyAnalyzer)
    """

    @abstractmethod
    def extract(self, text: str, context: dict[str, Any] | None = None) -> EmotionData:
        """
        Extract emotion information from text

        This is the core method that all analyzers must implement.

        Args:
            text: The text to analyze
            context: Optional context information, containing:
                - conversation_history: Conversation history
                - user_input: User input
                - user_state: User state
                - custom: Custom context

        Returns:
            EmotionData: Extracted emotion data, containing:
                - primary: Primary emotion
                - confidence: Confidence score (0.0 - 1.0)
                - timeline: Emotion timeline
                - metadata: Debug info

        Raises:
            NotImplementedError: Subclass must implement
            ValueError: Invalid input parameters

        Example:
            >>> analyzer.extract("What a wonderful day!")
            EmotionData(primary='happy', confidence=0.8, ...)
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Analyzer name (unique identifier)

        Used for factory registration and configuration references.
        Must be a globally unique string.

        Returns:
            str: Analyzer name

        Example:
            >>> analyzer.name
            'llm_tag_analyzer'
        """
        pass

    @property
    def priority(self) -> int:
        """
        Priority (lower number = higher priority)

        When multiple analyzers are used simultaneously, priority determines processing order.
        Default value is 100 (medium priority).

        Returns:
            int: Priority value (recommended range: 1-100)

        Example:
            >>> # High-priority analyzer
            >>> @property
            >>> def priority(self) -> int:
            ...     return 1
        """
        return 100

    def validate_input(self, text: str) -> bool:
        """
        Validate input parameters (optional method)

        Subclasses can override this method to add custom validation logic.

        Args:
            text: Text to validate

        Returns:
            bool: Whether the input is valid
        """
        return text is not None and len(text.strip()) > 0

    def get_supported_emotions(self) -> list[str]:
        """
        Get the list of supported emotions (optional method)

        Subclasses can override this method to declare supported emotions.

        Returns:
            List[str]: List of supported emotions
        """
        return []  # Empty list means all emotions are supported
