"""
Expression Parameter Mapper - Base Interface
Converts emotions/expressions to Live2D parameters
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ParameterState:
    """
    Live2D Parameter State

    Attributes:
        name: Parameter name (e.g., ParamMouthOpenY)
        value: Parameter value (typically range -1 to 1, or 0 to 1)
        duration: Transition duration (seconds)
    """

    name: str
    value: float
    duration: float = 0.3

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "duration": self.duration}


@dataclass
class ExpressionFrame:
    """
    Expression Frame

    Represents the complete expression state at a given moment, containing multiple parameters.

    Attributes:
        parameters: List of parameters
        intensity: Overall intensity (0.0 - 1.0)
        timestamp: Timestamp in seconds
    """

    parameters: list[ParameterState]
    intensity: float = 1.0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameters": [p.to_dict() for p in self.parameters],
            "intensity": self.intensity,
            "timestamp": self.timestamp,
        }


class IEmotionParamMapper(ABC):
    """
    Emotion Parameter Mapper Interface

    Maps emotion labels to Live2D model parameters.

    Design Patterns:
    - Strategy Pattern: Different mapping strategies
    - Plugin Pattern: Dynamically registerable mappers

    Usage Examples:
        >>> mapper = EmotionParamMapper()
        >>> frame = mapper.map_emotion("happy", intensity=0.8)
        >>> print(frame.parameters)
        [ParameterState('ParamMouthOpenY', 0.48, 0.3), ...]
    """

    @abstractmethod
    def map_emotion(
        self, emotion: str, intensity: float = 1.0, context: dict[str, Any] | None = None
    ) -> ExpressionFrame:
        """
        Map an emotion to Live2D parameters

        Args:
            emotion: Emotion name (e.g., "happy", "sad", "angry")
            intensity: Intensity (0.0 - 1.0)
            context: Optional context information

        Returns:
            ExpressionFrame: Expression frame containing all parameters

        Raises:
            ValueError: Unsupported emotion
        """
        pass

    @abstractmethod
    def map_emotions_timeline(
        self,
        emotions: list[tuple],  # [(emotion, start_time, end_time, intensity), ...]
        duration: float,
    ) -> list[ExpressionFrame]:
        """
        Map an emotion timeline to a sequence of expression frames

        Args:
            emotions: List of emotion segments
            duration: Total duration

        Returns:
            List[ExpressionFrame]: Sequence of expression frames
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Mapper name"""
        pass

    def get_supported_emotions(self) -> list[str]:
        """Get the list of supported emotions"""
        return []

    def apply_intensity(self, base_value: float, intensity: float) -> float:
        """
        Apply intensity coefficient

        Args:
            base_value: Base value
            intensity: Intensity (0.0 - 1.0)

        Returns:
            float: Value after applying intensity
        """
        return base_value * intensity
