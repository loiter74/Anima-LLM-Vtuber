"""Configuration for proactive livestream topic generation."""

from __future__ import annotations

from pydantic import Field, model_validator

from .core.base import BaseConfig


class ProactiveTopicsConfig(BaseConfig):
    """Bounded timing and delivery controls for autonomous host remarks."""

    enabled: bool = False
    initial_silence_seconds: float = Field(default=60.0, gt=0, le=3600)
    interval_min_seconds: float = Field(default=90.0, gt=0, le=3600)
    interval_max_seconds: float = Field(default=180.0, gt=0, le=3600)
    max_chars: int = Field(default=36, ge=2, le=36)

    @model_validator(mode="after")
    def validate_interval_range(self) -> ProactiveTopicsConfig:
        if self.interval_min_seconds > self.interval_max_seconds:
            raise ValueError("interval_min_seconds must not exceed interval_max_seconds")
        return self
