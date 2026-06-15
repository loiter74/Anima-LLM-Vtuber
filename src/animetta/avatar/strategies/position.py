"""
Position-based timeline strategy (enhanced version)

Allocates time based on the position of emotion tags in the text.
Implements the new ITimelineStrategy interface with enhanced error handling and features.
"""

from typing import Any

from loguru import logger

from .base import ITimelineStrategy, TimelineConfig, TimelineSegment


class PositionBasedStrategy(ITimelineStrategy):
    """
    Position-based timeline strategy

    Evenly allocates time based on the position of emotion tags in the text.
    Supports smooth transitions and custom intensity calculation.

    Features:
    - Evenly allocates time based on emotion list
    - Supports merging adjacent same emotions
    - Supports smooth transitions (transition_duration)
    - Supports custom intensity calculation
    - Comprehensive error handling and validation

    Attributes:
        config: Timeline configuration parameters
        enable_smoothing: Whether to enable smooth transitions

    Example:
        >>> strategy = PositionBasedStrategy(
        ...     enable_smoothing=True,
        ...     transition_duration=0.5
        ... )
        >>> segments = strategy.calculate(
        ...     emotions=["happy", "neutral", "sad"],
        ...     text="Hello world",
        ...     audio_duration=6.0
        ... )
        >>> print(len(segments))
        3
    """

    def __init__(
        self,
        config: TimelineConfig = None,
        enable_smoothing: bool = True
    ):
        """
        Initialize the strategy

        Args:
            config: Timeline configuration
            enable_smoothing: Whether to enable smooth transitions (merge adjacent same emotions)
        """
        self.config = config or TimelineConfig()
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
            config: Optional configuration (overrides instance config)
            **kwargs: Additional parameters (e.g., emotion_positions)

        Returns:
            List[TimelineSegment]: List of timeline segments

        Raises:
            ValueError: When input parameters are invalid
        """
        # Use provided config or instance config
        timeline_config = config or self.config

        # Validate input
        if not self.validate_input(emotions, text, audio_duration):
            raise ValueError(f"Invalid input parameters: emotions={emotions}, audio_duration={audio_duration}")

        try:
            # Case 1: No emotions
            if not emotions:
                logger.debug(f"[{self.name}] No emotions, using default emotion")
                return self._create_default_segment(
                    timeline_config.default_emotion,
                    audio_duration
                )

            # Case 2: Has emotions, distribute time evenly
            segments = self._calculate_even_segments(
                emotions,
                audio_duration,
                timeline_config
            )

            # Optional: Merge adjacent same emotions
            if self._enable_smoothing:
                segments = self.merge_adjacent_same_emotion(segments)

            # Ensure full coverage of audio duration
            segments = self.ensure_full_coverage(
                segments,
                audio_duration,
                timeline_config.default_emotion
            )

            # Apply minimum segment duration filter
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
            # Return default timeline
            return self._create_default_segment(
                timeline_config.default_emotion,
                audio_duration
            )

    def _calculate_even_segments(
        self,
        emotions: list[str],
        audio_duration: float,
        config: TimelineConfig
    ) -> list[TimelineSegment]:
        """
        Calculate evenly distributed segments

        Args:
            emotions: List of emotions
            audio_duration: Audio duration
            config: Timeline configuration

        Returns:
            List[TimelineSegment]: List of timeline segments
        """
        segment_duration = audio_duration / len(emotions)
        segments = []

        for i, emotion in enumerate(emotions):
            start_time = i * segment_duration
            end_time = (i + 1) * segment_duration

            # Calculate intensity (can be extended to be emotion-based)
            intensity = self._calculate_intensity(emotion, i, len(emotions))

            segments.append(TimelineSegment(
                emotion=emotion,
                start_time=start_time,
                end_time=end_time,
                intensity=intensity
            ))

        return segments

    def _calculate_intensity(
        self,
        emotion: str,
        _index: int,
        _total_emotions: int
    ) -> float:
        """
        Calculate emotion intensity

        Can calculate intensity based on emotion type, position, etc.
        Default returns fixed intensity 1.0.

        Args:
            emotion: Emotion name
            index: Index of emotion in the list
            total_emotions: Total number of emotions

        Returns:
            float: Intensity value (0.0 - 1.0)
        """
        # Default intensity
        return 1.0

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

        # If all segments were filtered, return the first segment
        if not filtered and segments:
            # Keep the longest segment
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
        return "position_based"

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
        # Check audio duration
        if not isinstance(audio_duration, (int, float)) or audio_duration <= 0:
            logger.warning(f"[{self.name}] Invalid audio duration: {audio_duration}")
            return False

        # Check text
        if not isinstance(text, str):
            logger.warning(f"[{self.name}] Invalid text type: {type(text)}")
            return False

        # Check emotions list
        if emotions is None:
            logger.warning(f"[{self.name}] Emotions list is None")
            return False

        return True

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
        for seg in segments:
            emotion_counts[seg.emotion] = emotion_counts.get(seg.emotion, 0) + 1

        return {
            "count": len(segments),
            "total_duration": sum(seg.duration for seg in segments),
            "emotions": list(emotion_counts.keys()),
            "emotion_counts": emotion_counts,
            "average_duration": sum(seg.duration for seg in segments) / len(segments),
            "min_duration": min(seg.duration for seg in segments),
            "max_duration": max(seg.duration for seg in segments)
        }
