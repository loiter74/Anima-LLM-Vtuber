"""
Emotion Parameter Mapper - Default Implementation
Maps common emotions to Live2D model parameters
"""

from typing import Any

from loguru import logger

from .base import ExpressionFrame, IEmotionParamMapper, ParameterState

# Default emotion parameter mapping configuration
DEFAULT_EMOTION_MAPPINGS = {
    "happy": {
        # Mouth: smiling
        "ParamMouthOpenY": 0.6,
        "ParamMouthForm": 0.3,
        # Eyebrows: raised
        "ParamEyebrowLY": 0.4,
        "ParamEyebrowRY": 0.4,
        # Eyes: wide, bright
        "ParamEyeLOpen": 0.95,
        "ParamEyeROpen": 0.95,
        "ParamEyeBallX": 0.0,
        "ParamEyeBallY": -0.1,
        # Head: slightly raised
        "ParamAngleX": -0.05,
        "ParamAngleY": 0.0,
        "ParamAngleZ": 0.0,
        # Body: slightly forward
        "ParamBodyAngleX": 0.05,
    },
    "sad": {
        # Mouth: slightly open, corners down
        "ParamMouthOpenY": 0.2,
        "ParamMouthForm": -0.2,
        # Eyebrows: lowered, pulled together
        "ParamEyebrowLY": -0.3,
        "ParamEyebrowRY": -0.3,
        # Eyes: half-closed
        "ParamEyeLOpen": 0.6,
        "ParamEyeROpen": 0.6,
        # Head: lowered
        "ParamAngleX": 0.15,
        "ParamAngleY": 0.0,
    },
    "angry": {
        # Mouth: tight or slightly open
        "ParamMouthOpenY": 0.3,
        "ParamMouthForm": 0.1,
        # Eyebrows: furrowed, lowered
        "ParamEyebrowLY": -0.6,
        "ParamEyebrowRY": -0.6,
        # Eyes: glaring
        "ParamEyeLOpen": 0.8,
        "ParamEyeROpen": 0.8,
        # Head: forward, slightly tilted
        "ParamAngleX": -0.1,
        "ParamAngleY": 0.15,
        "ParamAngleZ": 0.1,
    },
    "surprised": {
        # Mouth: open
        "ParamMouthOpenY": 0.7,
        "ParamMouthForm": 0.0,
        # Eyebrows: raised
        "ParamEyebrowLY": 0.5,
        "ParamEyebrowRY": 0.5,
        # Eyes: wide open
        "ParamEyeLOpen": 1.0,
        "ParamEyeROpen": 1.0,
        # Head: leaning back
        "ParamAngleX": -0.15,
        "ParamAngleY": 0.0,
    },
    "neutral": {
        # Default state
        "ParamMouthOpenY": 0.0,
        "ParamEyebrowLY": 0.0,
        "ParamEyebrowRY": 0.0,
        "ParamEyeLOpen": 0.85,
        "ParamEyeROpen": 0.85,
        "ParamAngleX": 0.0,
        "ParamAngleY": 0.0,
        "ParamAngleZ": 0.0,
    },
    "thinking": {
        # Mouth: slightly open
        "ParamMouthOpenY": 0.15,
        # Eyebrows: one up, one down (thinking pose)
        "ParamEyebrowLY": -0.2,
        "ParamEyebrowRY": 0.1,
        # Eyes: looking up
        "ParamEyeLOpen": 0.7,
        "ParamEyeROpen": 0.7,
        "ParamEyeBallY": 0.3,
        # Head: tilted, lowered
        "ParamAngleX": 0.1,
        "ParamAngleY": -0.1,
        "ParamAngleZ": 0.15,
    },
    "confused": {
        # Mouth: crooked
        "ParamMouthOpenY": 0.2,
        "ParamMouthForm": 0.3,
        # Eyebrows: pulled together
        "ParamEyebrowLY": 0.2,
        "ParamEyebrowRY": 0.2,
        # Eyes: squinting
        "ParamEyeLOpen": 0.7,
        "ParamEyeROpen": 0.7,
        # Head: tilted
        "ParamAngleZ": 0.2,
    },
    "love": {
        # Mouth: gentle smile
        "ParamMouthOpenY": 0.4,
        "ParamMouthForm": 0.2,
        # Eyebrows: softly raised
        "ParamEyebrowLY": 0.2,
        "ParamEyebrowRY": 0.2,
        # Eyes: gentle gaze
        "ParamEyeLOpen": 0.8,
        "ParamEyeROpen": 0.8,
        "ParamEyeBallY": -0.1,
        # Head: slightly tilted
        "ParamAngleY": -0.1,
    },
    "shy": {
        # Mouth: pursed
        "ParamMouthOpenY": 0.1,
        "ParamMouthForm": 0.1,
        # Eyebrows: lowered
        "ParamEyebrowLY": -0.1,
        "ParamEyebrowRY": -0.1,
        # Eyes: looking down
        "ParamEyeLOpen": 0.7,
        "ParamEyeROpen": 0.7,
        "ParamEyeBallY": 0.4,
        # Head: lowered, turned away
        "ParamAngleX": 0.2,
        "ParamAngleY": 0.15,
    },
    "excited": {
        # Mouth: laughing
        "ParamMouthOpenY": 0.8,
        "ParamMouthForm": 0.4,
        # Eyebrows: highly raised
        "ParamEyebrowLY": 0.6,
        "ParamEyebrowRY": 0.6,
        # Eyes: wide open
        "ParamEyeLOpen": 1.0,
        "ParamEyeROpen": 1.0,
        # Head: leaning back
        "ParamAngleX": -0.1,
        # Body: leaning forward
        "ParamBodyAngleX": 0.1,
    },
}


class EmotionParamMapper(IEmotionParamMapper):
    """
    Emotion Parameter Mapper

    Maps emotion labels to Live2D model parameters.
    Supports custom mapping configuration.

    Attributes:
        mappings: Dictionary mapping emotions to parameters
        default_duration: Default transition duration (seconds)

    Example:
        >>> mapper = EmotionParamMapper()
        >>> frame = mapper.map_emotion("happy", intensity=0.8)
        >>> for param in frame.parameters:
        ...     print(f"{param.name}: {param.value}")
    """

    def __init__(
        self, mappings: dict[str, dict[str, float]] | None = None, default_duration: float = 0.3
    ):
        """
        Initialize the mapper

        Args:
            mappings: Custom mapping configuration (defaults to DEFAULT_EMOTION_MAPPINGS)
            default_duration: Default transition duration
        """
        self.mappings = mappings or DEFAULT_EMOTION_MAPPINGS
        self.default_duration = default_duration

    def map_emotion(
        self, emotion: str, intensity: float = 1.0, context: dict[str, Any] | None = None
    ) -> ExpressionFrame:
        """
        Map an emotion to Live2D parameters

        Args:
            emotion: Emotion name
            intensity: Intensity (0.0 - 1.0)
            context: Context information

        Returns:
            ExpressionFrame: Expression frame
        """
        emotion_lower = emotion.lower()

        if emotion_lower not in self.mappings:
            logger.warning(f"[EmotionParamMapper] Unknown emotion: {emotion}, using neutral")
            emotion_lower = "neutral"

        param_config = self.mappings[emotion_lower]

        # Create parameters list
        parameters = []
        for param_name, base_value in param_config.items():
            # Apply intensity
            value = self.apply_intensity(base_value, intensity)

            # Add random variance (avoid mechanical feel)
            value = self._add_variance(value, intensity)

            parameters.append(
                ParameterState(name=param_name, value=value, duration=self.default_duration)
            )

        return ExpressionFrame(parameters=parameters, intensity=intensity, timestamp=0.0)

    def map_emotions_timeline(
        self, emotions: list[tuple[str, float, float, float]], duration: float
    ) -> list[ExpressionFrame]:
        """
        Map an emotion timeline to a sequence of expression frames

        Args:
            emotions: [(emotion, start_time, end_time, intensity), ...]
            duration: Total duration

        Returns:
            List[ExpressionFrame]: Sequence of expression frames
        """
        frames = []

        for emotion, start_time, end_time, intensity in emotions:
            frame = self.map_emotion(emotion, intensity)
            frame.timestamp = start_time

            # Update parameter duration to segment duration
            for param in frame.parameters:
                param.duration = end_time - start_time

            frames.append(frame)

        # Sort by timestamp
        frames.sort(key=lambda f: f.timestamp)

        return frames

    def _add_variance(self, value: float, intensity: float) -> float:
        """
        Add random variance

        Makes expressions more natural, avoiding mechanical feel.

        Args:
            value: Base value
            intensity: Intensity

        Returns:
            float: Value after adding variance
        """
        import random

        # Variance range decreases with intensity
        variance = 0.05 * intensity

        if variance > 0:
            value += random.uniform(-variance, variance)

        # Clamp to valid range
        return max(-1.0, min(1.0, value))

    @property
    def name(self) -> str:
        return "emotion_param_mapper"

    def get_supported_emotions(self) -> list[str]:
        """Get supported emotions list"""
        return list(self.mappings.keys())

    def add_emotion_mapping(self, emotion: str, param_mappings: dict[str, float]) -> None:
        """
        Add or update emotion mapping

        Args:
            emotion: Emotion name
            param_mappings: Parameter mapping dictionary
        """
        self.mappings[emotion.lower()] = param_mappings

    def load_from_yaml(self, yaml_path: str) -> None:
        """
        Load mapping configuration from YAML file

        Args:
            yaml_path: YAML file path
        """
        from pathlib import Path

        import yaml

        path = Path(yaml_path)
        if not path.exists():
            logger.error(f"[EmotionParamMapper] Config file not found: {yaml_path}")
            return

        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if "emotions" in config:
            self.mappings.update(config["emotions"])
            logger.info(
                f"[EmotionParamMapper] Loaded {len(config['emotions'])} emotion mappings from {yaml_path}"
            )
