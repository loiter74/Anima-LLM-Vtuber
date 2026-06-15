"""
Timeline Strategy Interface and Basic Data Structures

Defines the interface for emotion timeline calculation strategies.
Uses the strategy pattern to support different time allocation algorithms.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class TimelineSegment:
    """
    Timeline Segment

    Represents the emotional state within a specific time period.
    Multiple segments combine to form a complete timeline.

    Attributes:
        emotion: Emotion name (e.g., "happy", "sad")
        start_time: Start time (seconds)
        end_time: End time (seconds)
        intensity: Emotion intensity (0.0 - 1.0, default 1.0)

    Example:
        >>> segment = TimelineSegment("happy", 0.0, 2.5, intensity=0.8)
        >>> segment.to_dict()
        {'emotion': 'happy', 'time': 0.0, 'duration': 2.5}
        >>> segment.duration
        2.5
    """
    emotion: str
    start_time: float
    end_time: float
    intensity: float = 1.0

    @property
    def duration(self) -> float:
        """Calculate segment duration"""
        return self.end_time - self.start_time

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary (for WebSocket messages)

        Returns:
            Dict[str, Any]: Dictionary format usable by the frontend (includes intensity)
        """
        return {
            "emotion": self.emotion,
            "time": self.start_time,
            "duration": self.duration,
            "intensity": self.intensity
        }

    def to_frontend_format(self) -> dict[str, Any]:
        """
        Convert to frontend format (compatible with audio_with_expression event)

        Returns:
            Dict[str, Any]: Dictionary containing emotion, time, duration, intensity
        """
        return {
            "emotion": self.emotion,
            "time": self.start_time,
            "duration": self.duration,
            "intensity": self.intensity
        }

    def __repr__(self) -> str:
        """String representation"""
        return (f"TimelineSegment(emotion={self.emotion}, "
                f"start={self.start_time:.2f}s, "
                f"end={self.end_time:.2f}s, "
                f"intensity={self.intensity:.2f})")

    def contains_time(self, time: float) -> bool:
        """
        Check if a specific time is within the segment

        Args:
            time: Time point (seconds)

        Returns:
            bool: True if the time is within the segment range
        """
        return self.start_time <= time < self.end_time

    def overlaps_with(self, other: 'TimelineSegment') -> bool:
        """
        Check if this segment overlaps with another segment

        Args:
            other: Another timeline segment

        Returns:
            bool: True if the two segments overlap
        """
        return not (self.end_time <= other.start_time or
                   self.start_time >= other.end_time)


@dataclass
class TimelineConfig:
    """
    Timeline Configuration Parameters

    Used to configure the behavior of timeline calculation.

    Attributes:
        default_emotion: Default emotion (used when no emotion is present)
        min_segment_duration: Minimum segment duration (seconds)
        transition_duration: Transition duration (seconds)
        enable_smoothing: Whether to enable smooth transitions
    """
    default_emotion: str = "neutral"
    min_segment_duration: float = 0.1
    transition_duration: float = 0.3
    enable_smoothing: bool = True

    def validate(self) -> bool:
        """Validate configuration parameters"""
        return (
            self.min_segment_duration >= 0
            and self.transition_duration >= 0
            and len(self.default_emotion) > 0
        )


class ITimelineStrategy(ABC):
    """
    Timeline Calculation Strategy Interface

    Defines how to map emotions to a timeline.
    Different strategies can implement different time allocation algorithms.

    Design Patterns:
    - Strategy Pattern: Different timeline calculation strategies
    - Extensible: Easily add new calculation strategies

    Usage Examples:
        >>> strategy = PositionBasedStrategy()
        >>> segments = strategy.calculate(
        ...     emotions=["happy", "neutral"],
        ...     text="Hello world",
        ...     audio_duration=5.0
        ... )
        >>> print(segments)
        [TimelineSegment(happy, 0.0, 2.5, 1.0), TimelineSegment(neutral, 2.5, 5.0, 1.0)]

    Extension Example:
        >>> class MyStrategy(ITimelineStrategy):
        ...     def calculate(self, emotions, text, audio_duration, **kwargs):
        ...         # Custom time allocation logic
        ...         return [TimelineSegment(emotion, 0.0, audio_duration)]
        ...
        >>> from anima.avatar.factory import TimelineStrategyFactory
        >>> TimelineStrategyFactory.register("my_strategy", MyStrategy)
    """

    @abstractmethod
    def calculate(
        self,
        emotions: list[str],
        text: str,
        audio_duration: float,
        config: TimelineConfig = None,
        **_kwargs
    ) -> list[TimelineSegment]:
        """
        Calculate the emotion timeline

        This is the core method that all strategies must implement.

        Args:
            emotions: List of emotions (extracted by IEmotionAnalyzer)
            text: Text content (for semantic analysis)
            audio_duration: Audio duration (seconds)
            config: Optional configuration parameters
            **kwargs: Additional parameters (for future extension)

        Returns:
            List[TimelineSegment]: List of timeline segments
                - Segments are sorted by time
                - Segments should cover the entire audio duration
                - Segments can have gaps or overlap

        Raises:
            NotImplementedError: Subclass must implement
            ValueError: Invalid parameters

        Example:
            >>> strategy.calculate(
            ...     emotions=["happy", "neutral"],
            ...     text="Hello world",
            ...     audio_duration=10.0
            ... )
            [
                TimelineSegment(emotion="happy", start_time=0.0, end_time=5.0),
                TimelineSegment(emotion="neutral", start_time=5.0, end_time=10.0)
            ]
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Strategy name (unique identifier)

        Used for factory registration and configuration references.
        Must be a globally unique string.

        Returns:
            str: Strategy name

        Example:
            >>> strategy.name
            'position_based'
        """
        pass

    def validate_input(
        self,
        emotions: list[str],
        text: str,
        audio_duration: float
    ) -> bool:
        """
        Validate input parameters (optional method)

        Subclasses can override this method to add custom validation.

        Args:
            emotions: List of emotions
            text: Text content
            audio_duration: Audio duration

        Returns:
            bool: Whether the input is valid
        """
        return (
            audio_duration > 0
            and text is not None
            and len(text) >= 0
        )

    def ensure_full_coverage(
        self,
        segments: list[TimelineSegment],
        audio_duration: float,
        default_emotion: str = "neutral"
    ) -> list[TimelineSegment]:
        """
        Ensure the timeline covers the entire audio duration

        If there are gaps in the timeline, fill them with the default emotion.
        This is a helper method that subclasses can use.

        Args:
            segments: Original timeline segments
            audio_duration: Audio duration
            default_emotion: Default emotion

        Returns:
            List[TimelineSegment]: The filled, complete timeline
        """
        if not segments:
            return [
                TimelineSegment(
                    emotion=default_emotion,
                    start_time=0.0,
                    end_time=audio_duration
                )
            ]

        # Sort by start time
        sorted_segments = sorted(segments, key=lambda s: s.start_time)

        # Check for gaps
        result = []
        last_end = 0.0

        for segment in sorted_segments:
            # If there's a gap, fill with default emotion
            if segment.start_time > last_end:
                result.append(TimelineSegment(
                    emotion=default_emotion,
                    start_time=last_end,
                    end_time=segment.start_time
                ))

            result.append(segment)
            last_end = max(last_end, segment.end_time)

        # Check if end is covered
        if last_end < audio_duration:
            result.append(TimelineSegment(
                emotion=default_emotion,
                start_time=last_end,
                end_time=audio_duration
            ))

        return result

    def merge_adjacent_same_emotion(
        self,
        segments: list[TimelineSegment]
    ) -> list[TimelineSegment]:
        """
        Merge adjacent segments with the same emotion

        This is a helper method that subclasses can use.
        Reduces segment count and improves performance.

        Args:
            segments: Original timeline segments

        Returns:
            List[TimelineSegment]: Merged timeline
        """
        if not segments:
            return []

        # Sort by time
        sorted_segments = sorted(segments, key=lambda s: s.start_time)

        result = []
        current = sorted_segments[0]

        for next_seg in sorted_segments[1:]:
            # If same emotion and overlapping or adjacent, merge
            if (next_seg.emotion == current.emotion and
                next_seg.start_time <= current.end_time):
                current = TimelineSegment(
                    emotion=current.emotion,
                    start_time=current.start_time,
                    end_time=max(current.end_time, next_seg.end_time),
                    intensity=max(current.intensity, next_seg.intensity)
                )
            else:
                result.append(current)
                current = next_seg

        result.append(current)
        return result
