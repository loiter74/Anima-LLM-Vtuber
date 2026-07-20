"""Configuration for room-level livestream scene analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .core.base import BaseConfig


class SceneAnalysisConfig(BaseConfig):
    """Bounded controls for cached scene reflection and prompt injection."""

    mode: Literal["off", "shadow", "active"] = "shadow"
    reflection_interval_seconds: float = Field(default=30.0, gt=0, le=600)
    event_threshold: int = Field(default=30, ge=1, le=1000)
    max_reflections_per_minute: int = Field(default=4, ge=1, le=60)
    guidance_wait_seconds: float = Field(default=0.3, ge=0, le=2)
    model_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    model_max_tokens: int = Field(default=800, ge=100, le=4000)
