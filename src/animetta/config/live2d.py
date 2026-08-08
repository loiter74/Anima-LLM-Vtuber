"""
Live2D configuration class
Defines Live2D model configuration and expression mapping
"""

from pathlib import Path

from pydantic import BaseModel, Field

from .core.base import BaseConfig


class Live2DModelConfig(BaseModel):
    """Live2D model configuration"""

    path: str = Field(default="/live2d/mao/Mao.model3.json", description="Model file path")
    scale: float = Field(default=0.5, description="Model scale ratio")
    position: dict[str, float] = Field(
        default_factory=lambda: {"x": 0.0, "y": 0.0}, description="Model position (x, y)"
    )


class Live2DLipSyncConfig(BaseModel):
    """Live2D lip sync configuration"""

    enabled: bool = Field(default=True, description="Whether to enable lip sync")
    sensitivity: float = Field(
        default=1.0, ge=0.0, le=2.0, description="Mouth movement sensitivity"
    )
    smoothing: float = Field(default=0.5, ge=0.0, le=1.0, description="Smoothing factor")


class Live2DConfig(BaseConfig):
    """
    Live2D configuration

    Emotion-based Live2D expression control
    """

    # Whether to enable Live2D
    enabled: bool = Field(default=True, description="Whether to enable Live2D")

    # Model configuration
    model: Live2DModelConfig = Field(
        default_factory=Live2DModelConfig, description="Live2D model configuration"
    )

    # Emotion mapping: emotion name → Live2D motion index
    # Example: {"happy": 3, "sad": 1, "angry": 2}
    emotion_map: dict[str, int] = Field(
        default_factory=lambda: {
            "happy": 3,
            "sad": 1,
            "angry": 2,
            "surprised": 4,
            "neutral": 0,
            "thinking": 5,
        },
        description="Mapping from emotion name to Live2D motion index",
    )

    # Valid emotion list (for prompts)
    valid_emotions: list[str] = Field(
        default_factory=lambda: ["happy", "sad", "angry", "surprised", "neutral", "thinking"],
        description="List of valid emotions",
    )

    # Lip sync configuration
    lip_sync: Live2DLipSyncConfig = Field(
        default_factory=Live2DLipSyncConfig, description="Lip sync configuration"
    )

    # Prompt template path
    prompt_template_path: str = Field(
        default="config/prompts/live2d_expression.txt",
        description="Expression usage guide prompt template path",
    )

    @classmethod
    def from_yaml(cls, path: str) -> "Live2DConfig":
        """
        Load configuration from YAML file

        Args:
            path: Configuration file path

        Returns:
            Live2DConfig instance
        """
        import yaml

        config_path = Path(path)
        if not config_path.exists():
            logger.warning(f"Live2D config file not found: {config_path}, using default config")
            return cls()

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def get_emotion_names(self) -> list[str]:
        """Get list of all emotion names"""
        return list(self.emotion_map.keys())

    def get_motion_index(self, emotion: str) -> int | None:
        """
        Get the Live2D motion index for an emotion

        Args:
            emotion: Emotion name

        Returns:
            Motion index, or None if not found
        """
        return self.emotion_map.get(emotion)

    def is_valid_emotion(self, emotion: str) -> bool:
        """
        Check if an emotion is valid

        Args:
            emotion: Emotion name

        Returns:
            Whether valid
        """
        return emotion in self.emotion_map


# Global Live2D config instance (lazy loaded)
_live2d_config: Live2DConfig | None = None


def get_live2d_config() -> Live2DConfig:
    """
    Get global Live2D configuration (singleton)

    Returns:
        Live2DConfig instance
    """
    global _live2d_config
    if _live2d_config is None:
        config_path = Path("config/features/live2d.yaml")
        if config_path.exists():
            _live2d_config = Live2DConfig.from_yaml(str(config_path))
        else:
            _live2d_config = Live2DConfig()
    return _live2d_config


def reset_live2d_config() -> None:
    """Reset global Live2D configuration (for testing)"""
    global _live2d_config
    _live2d_config = None


# Import logger
from loguru import logger
