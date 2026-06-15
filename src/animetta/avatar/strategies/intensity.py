"""
Intensity-based timeline strategy

Calculates timeline segments based on emotion intensity.
High-intensity emotions get more time and higher intensity values.
"""

from typing import Any

from loguru import logger

from .base import ITimelineStrategy, TimelineConfig, TimelineSegment


class IntensityBasedStrategy(ITimelineStrategy):
    """
    Intensity-based timeline strategy

    Allocates time and sets intensity values based on emotion intensity.
    Different emotions have different default intensities, which can be customized.

    Features:
    - Different emotions have different intensity values
    - High-intensity emotions get more time
    - Supports custom emotion intensity mapping
    - Supports intensity threshold filtering
    - Supports smooth transitions

    Attributes:
        config: Timeline configuration
        emotion_intensities: Emotion intensity mapping (0.0 - 1.0)
        min_intensity: Minimum intensity threshold (emotions below this are filtered)
        intensity_factor: Intensity's influence on time allocation (0.0 - 1.0)

    Example:
        >>> strategy = IntensityBasedStrategy(
        ...     intensity_factor=0.8
        ... )
        >>> segments = strategy.calculate(
        ...     emotions=["happy", "sad", "surprised"],
        ...     text="I'm happy sad and surprised",
        ...     audio_duration=9.0
        ... )
        >>> # High-intensity emotions (e.g., surprised) get more time
    """

    # Default emotion intensity values (0.0 - 1.0)
    DEFAULT_EMOTION_INTENSITIES = {
        "happy": 0.8,          # High intensity
        "sad": 0.6,            # Medium intensity
        "angry": 0.9,          # Very high intensity
        "surprised": 0.95,     # Extremely high intensity (short but strong)
        "thinking": 0.4,       # Lower intensity
        "neutral": 0.3,        # Low intensity
        "listening": 0.3,      # Low intensity
        "speaking": 0.7,       # Medium-high intensity
    }

    def __init__(
        self,
        config: TimelineConfig = None,
        emotion_intensities: dict[str, float] | None = None,
        min_intensity: float = 0.2,
        intensity_factor: float = 0.5,
        enable_smoothing: bool = True
    ):
        """
        Initialize the strategy

        Args:
            config: Timeline configuration
            emotion_intensities: Custom emotion intensity mapping
            min_intensity: Minimum intensity threshold (emotions below this are filtered)
            intensity_factor: Intensity's influence on time allocation (0.0 = no influence, 1.0 = full influence)
            enable_smoothing: Whether to enable smooth transitions
        """
        self.config = config or TimelineConfig()
        self._emotion_intensities = emotion_intensities or self.DEFAULT_EMOTION_INTENSITIES.copy()
        self._min_intensity = min_intensity
        self._intensity_factor = max(0.0, min(1.0, intensity_factor))
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
        timeline_config = config or self.config

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

            # Case 2: Allocate time and intensity based on intensity values
            segments = self._calculate_intensity_segments(
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

            # Apply minimum intensity filter
            segments = self._filter_low_intensity_segments(
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

    def _calculate_intensity_segments(
        self,
        emotions: list[str],
        audio_duration: float,
        config: TimelineConfig
    ) -> list[TimelineSegment]:
        """
        Calculate time allocation and intensity values based on intensity

        Args:
            emotions: List of emotions
            audio_duration: Audio duration
            config: Timeline configuration

        Returns:
            List[TimelineSegment]: List of timeline segments
        """
        # Get intensity for each emotion
        intensities = []
        for emotion in emotions:
            intensity = self._emotion_intensities.get(emotion, 0.5)
            intensities.append(intensity)

        # Filter low-intensity emotions
        filtered_emotions = []
        filtered_intensities = []
        for emotion, intensity in zip(emotions, intensities):
            if intensity >= self._min_intensity:
                filtered_emotions.append(emotion)
                filtered_intensities.append(intensity)
            else:
                logger.debug(
                    f"[{self.name}] Filtering low-intensity emotion: {emotion} ({intensity:.2f})"
                )

        # If all emotions were filtered, use default emotion
        if not filtered_emotions:
            return self._create_default_segment(config.default_emotion, audio_duration)

        # Calculate weighted intensity (considering intensity_factor)
        # intensity_factor = 0.0: all emotions get equal time
        # intensity_factor = 1.0: fully proportional to intensity
        if self._intensity_factor == 0.0:
            # Equal distribution
            weights = [1.0] * len(filtered_emotions)
        else:
            # Distribute by intensity, but consider intensity_factor
            base_weights = [1.0] * len(filtered_emotions)
            intensity_weights = filtered_intensities
            weights = [
                (1 - self._intensity_factor) * base + self._intensity_factor * intensity
                for base, intensity in zip(base_weights, intensity_weights)
            ]

        total_weight = sum(weights)

        # Allocate time based on weights
        segments = []
        current_time = 0.0

        for i, (emotion, intensity, weight) in enumerate(zip(
            filtered_emotions,
            filtered_intensities,
            weights
        )):
            # Calculate duration
            if total_weight == 0:
                duration = audio_duration / len(filtered_emotions)
            else:
                duration = (weight / total_weight) * audio_duration

            start_time = current_time
            end_time = current_time + duration

            # Last emotion extends to end of audio
            if i == len(filtered_emotions) - 1:
                end_time = audio_duration

            segments.append(TimelineSegment(
                emotion=emotion,
                start_time=start_time,
                end_time=end_time,
                intensity=intensity  # Use emotion's intensity value
            ))

            current_time = end_time

            if current_time >= audio_duration:
                break

        return segments

    def _filter_low_intensity_segments(
        self,
        segments: list[TimelineSegment],
        min_duration: float
    ) -> list[TimelineSegment]:
        """
        Filter out segments with low intensity or short duration

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

        if not filtered and segments:
            # Keep the segment with the highest intensity
            highest = max(segments, key=lambda s: s.intensity)
            return [highest]

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
                intensity=0.5  # Default medium intensity
            )
        ]

    @property
    def name(self) -> str:
        """Strategy name"""
        return "intensity_based"

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

    def set_emotion_intensity(self, emotion: str, intensity: float) -> None:
        """
        Set the intensity value for an emotion

        Args:
            emotion: Emotion name
            intensity: Intensity value (0.0 - 1.0)
        """
        if not 0.0 <= intensity <= 1.0:
            raise ValueError(f"Intensity value must be between 0.0 - 1.0: {intensity}")

        self._emotion_intensities[emotion] = intensity
        logger.debug(f"[{self.name}] Set intensity for {emotion} to {intensity}")

    def get_emotion_intensity(self, emotion: str) -> float:
        """
        Get the intensity value for an emotion

        Args:
            emotion: Emotion name

        Returns:
            float: Intensity value, returns 0.5 if not found
        """
        return self._emotion_intensities.get(emotion, 0.5)

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
                "average_duration": 0.0,
                "average_intensity": 0.0
            }

        emotion_counts: dict[str, int] = {}
        emotion_durations: dict[str, float] = {}
        emotion_intensities: dict[str, list[float]] = {}

        for seg in segments:
            emotion_counts[seg.emotion] = emotion_counts.get(seg.emotion, 0) + 1
            emotion_durations[seg.emotion] = emotion_durations.get(seg.emotion, 0.0) + seg.duration

            # Record intensity (take average)
            if seg.emotion not in emotion_intensities:
                emotion_intensities[seg.emotion] = []
            emotion_intensities[seg.emotion].append(seg.intensity)

        # Calculate average intensity
        avg_intensities = {
            emotion: sum(intensities) / len(intensities)
            for emotion, intensities in emotion_intensities.items()
        }

        return {
            "count": len(segments),
            "total_duration": sum(seg.duration for seg in segments),
            "emotions": list(emotion_counts.keys()),
            "emotion_counts": emotion_counts,
            "emotion_durations": emotion_durations,
            "average_intensity": sum(seg.intensity for seg in segments) / len(segments),
            "emotion_intensities": avg_intensities,
            "average_duration": sum(seg.duration for seg in segments) / len(segments),
            "min_duration": min(seg.duration for seg in segments),
            "max_duration": max(seg.duration for seg in segments)
        }
