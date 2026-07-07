"""Configuration for the Humor Agent pipeline."""

from __future__ import annotations

from pydantic import Field

from animetta.config.core.base import BaseConfig

DEFAULT_ALLOWED_STYLES = ["affiliative", "self-enhancing"]
DEFAULT_WORLDVIEW_HINTS = ["cyber tavern", "working AI", "demon castle"]


class HumorConfig(BaseConfig):
    """Runtime controls for Anima's humorous reply rewrite pipeline."""

    enabled: bool = Field(
        default=False,
        description="Enable post-response humor rewriting.",
    )
    max_candidate_chars: int = Field(
        default=180,
        ge=20,
        le=600,
        description="Maximum visible candidate response length.",
    )
    candidate_count: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Number of candidates to request from the rewrite model.",
    )
    timeout_seconds: float = Field(
        default=8.0,
        gt=0,
        le=60,
        description="Timeout for the internal Humor Agent LLM call.",
    )
    allowed_styles: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_STYLES),
        description="Humor styles allowed for live viewer interaction.",
    )
    worldview_hints: list[str] = Field(
        default_factory=lambda: list(DEFAULT_WORLDVIEW_HINTS),
        description="Anima worldview motifs available to the rewrite prompt.",
    )

