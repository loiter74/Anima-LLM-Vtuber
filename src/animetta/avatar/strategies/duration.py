"""
Duration-based timeline strategy

Allocates different durations based on emotion type.
Some emotions (e.g., sad) may need longer expression time.
"""

from typing import Any

from loguru import logger

from .base import ITimelineStrategy, TimelineConfig, TimelineSegment


class DurationBasedStrategy(ITimelineStrategy):
    """
    Duration-based timeline strategy

    Allocates different durations based on emotion type.
    Different emotions have different weights affecting their duration.

    Features:
    - Different emotions have different time weights
    - Supports custom emotion duration mapping
    - Supports min and max duration limits
    - Supports smooth transitions and merging same emotions

    Attributes:
        config: Timeline configuration
        duration_weights: Emotion duration weight mapping
        min_emotion_duration: Minimum duration for a single emotion
        max_emotion_duration: Maximum duration for a single emotion

    Example:
        >>> strategy = DurationBasedStrategy()
        >>> segments = strategy.calculate(
        ...     emotions=["happy", "sad", "happy"],
        ...     text="I'm happy but sad then happy",
        ...     audio_duration=10.0
        ... )
        >>> # sad will be allocated longer time
    """

    # Default emotion duration weights (multiplier relative to other emotions)
    DEFAULT_DURATION_WEIGHTS = {
        "happy": 1.0,        # Standard duration
        "sad": 1.5,          # Sad emotions last longer
        "angry": 1.2,        # Anger lasts slightly longer
        "surprised": 0.8,    # Surprise is shorter
        "thinking": 1.3,     # Thinking takes time
        "neutral": 1.0,      # Neutral standard duration
        "listening": 1.0,    # Listening state
        "speaking": 1.0,     # Speaking state
    }

    def __init__(
        self,
        config: TimelineConfig = None,
        duration_weights: dict[str, float] | None = None,
        min_emotion_duration: float = 0.5,
        max_emotion_duration: float = 5.0,
        enable_smoothing: bool = True
    ):
        """
        Initialize the strategy

        Args:
            config: Timeline configuration
            duration_weights: Custom emotion duration weights
            min_emotion_duration: Minimum duration for a single emotion (seconds)
            max_emotion_duration: Maximum duration for a single emotion (seconds)
            enable_smoothing: Whether to enable smooth transitions
        """
        self.core.config = config or TimelineConfig()
        self._duration_weights = duration_weights or self.DEFAULT_DURATION_WEIGHTS.copy()
        self._min_emotion_duration = min_emotion_duration
        self._max_emotion_duration = max_emotion_duration
        self._enable_smoothing = enable_smoothing

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

        Args:
            emotions: List of emotions
            text: Text content
            audio_duration: Audio duration
            config: Optional configuration
            **kwargs: Additional parameters

        Returns:
            List[TimelineSegment]: List of timeline segments

        Raises:
            ValueError: When input parameters are invalid
        """
        timeline_config = config or self.core.config

        # Validate input
        if not self.validate_input(emotions, text, audio_duration):
            raise ValueError("Invalid input parameters")

        try:
            # Case 1: No emotions
            if not emotions:
                logger.debug(f"[{self.name}] No emotions, using default emotion")
                return self._create_default_segment(
                    timeline_config.default_emotion,
                    audio_duration
                )

            # Case 2: Allocate time based on weights
            segments = self._calculate_weighted_segments(
                emotions,
                audio_duration,
                timeline_config
            )

            # Optional: Merge adjacent same emotions
            if self._enable_smoothing:
                segments = self.merge_adjacent_same_emotion(segments)

            # Ensure full coverage
            segments = self.ensure_full_coverage(
                segments,
                audio_duration,
                timeline_config.default_emotion
            )

            # Apply minimum duration filter
            segments = self._filter_short_segments(
                segments,
                timeline_config.min_segment_duration
            )

            logger.debug(
                f"[{self.name}] Calculated {len(segments)} timeline segments, "
                f"total duration {audio_duration:.2f}s"
            )

            return segments

        except Exception as e:
            logger.error(f"[{self.name}] Failed to calculate timeline: {e}")
            return self._create_default_segment(
                timeline_config.default_emotion,
                audio_duration
            )

    def _calculate_weighted_segments(
        self,
        emotions: list[str],
        audio_duration: float,
        config: TimelineConfig
    ) -> list[TimelineSegment]:
        """
        Calculate time allocation based on weights

        Args:
            emotions: List of emotions
            audio_duration: Audio duration
            config: Timeline configuration

        Returns:
            List[TimelineSegment]: List of timeline segments
        """
        # Calculate weight for each emotion
        weights = []
        for emotion in emotions:
            weight = self._duration_weights.get(emotion, 1.0)
            weights.append(weight)

        # Calculate total weight
        total_weight = sum(weights)

        # If total weight is 0, distribute evenly
        len(emotions) if total_weight == 0 else total_weight

        # Allocate time based on weights
        segments = []
        current_time = 0.0

        for i, (emotion, weight) in enumerate(zip(emotions, weights)):
            # Calculate duration
            if total_weight == 0:
                duration = audio_duration / len(emotions)
            else:
                duration = (weight / total_weight) * audio_duration

            # Apply min and max limits
            duration = max(duration, self._min_emotion_duration)
            duration = min(duration, self._max_emotion_duration)

            start_time = current_time
            end_time = current_time + duration

            # Last emotion extends to end of audio
            if i == len(emotions) - 1:
                end_time = audio_duration

            segments.append(TimelineSegment(
                emotion=emotion,
                start_time=start_time,
                end_time=end_time,
                intensity=1.0
            ))

            current_time = end_time

            # If exceeds audio duration, stop
            if current_time >= audio_duration:
                break

        return segments

    def _filter_short_segments(
        self,
        segments: list[TimelineSegment],
        min_duration: float
    ) -> list[TimelineSegment]:
        """
        Filter out segments that are too short

        Args:
            segments: List of timeline segments
            min_duration: Minimum duration

        Returns:
            List[TimelineSegment]: Filtered segment list
        """
        filtered = []
        for segment in segments:
            if segment.duration >= min_duration:
                filtered.append(segment)
            else:
                logger.debug(
                    f"[{self.name}] Skipping too short emotion segment: "
                    f"{segment.emotion} ({segment.duration:.3f}s)"
                )

        # If all segments were filtered, keep the longest
        if not filtered and segments:
            longest = max(segments, key=lambda s: s.duration)
            return [longest]

        return filtered

    def _create_default_segment(
        self,
        emotion: str,
        duration: float
    ) -> list[TimelineSegment]:
        """
        Create a default timeline segment

        Args:
            emotion: Emotion name
            duration: Duration

        Returns:
            List[TimelineSegment]: List containing a single segment
        """
        return [
            TimelineSegment(
                emotion=emotion,
                start_time=0.0,
                end_time=duration,
                intensity=1.0
            )
        ]

    @property
    def name(self) -> str:
        """Strategy name"""
        return "duration_based"

    def validate_input(
        self,
        emotions: list[str],
        text: str,
        audio_duration: float
    ) -> bool:
        """
        Validate input parameters

        Args:
            emotions: List of emotions
            text: Text content
            audio_duration: Audio duration

        Returns:
            bool: Whether valid
        """
        if not isinstance(audio_duration, (int, float)) or audio_duration <= 0:
            logger.warning(f"[{self.name}] Invalid audio duration: {audio_duration}")
            return False

        if not isinstance(text, str):
            logger.warning(f"[{self.name}] Invalid text type: {type(text)}")
            return False

        if emotions is None:
            logger.warning(f"[{self.name}] Emotions list is None")
            return False

        return True

    def set_duration_weight(self, emotion: str, weight: float) -> None:
        """
        Set the duration weight for an emotion

        Args:
            emotion: Emotion name
            weight: Weight value (must be > 0)
        """
        if weight <= 0:
            raise ValueError(f"Weight must be greater than 0: {weight}")

        self._duration_weights[emotion] = weight
        logger.debug(f"[{self.name}] Set weight for {emotion} to {weight}")

    def get_duration_weight(self, emotion: str) -> float:
        """
        Get the duration weight for an emotion

        Args:
            emotion: Emotion name

        Returns:
            float: Weight value, returns 1.0 if not found
        """
        return self._duration_weights.get(emotion, 1.0)

    def get_segment_info(self, segments: list[TimelineSegment]) -> dict[str, Any]:
        """
        Get statistics for timeline segments

        Args:
            segments: List of timeline segments

        Returns:
            Dict: Statistics
        """
        if not segments:
            return {
                "count": 0,
                "total_duration": 0.0,
                "emotions": [],
                "average_duration": 0.0
            }

        emotion_counts: dict[str, int] = {}
        emotion_durations: dict[str, float] = {}

        for seg in segments:
            emotion_counts[seg.emotion] = emotion_counts.get(seg.emotion, 0) + 1
            emotion_durations[seg.emotion] = emotion_durations.get(seg.emotion, 0.0) + seg.duration

        return {
            "count": len(segments),
            "total_duration": sum(seg.duration for seg in segments),
            "emotions": list(emotion_counts.keys()),
            "emotion_counts": emotion_counts,
            "emotion_durations": emotion_durations,
            "average_duration": sum(seg.duration for seg in segments) / len(segments),
            "min_duration": min(seg.duration for seg in segments),
            "max_duration": max(seg.duration for seg in segments)
        }
