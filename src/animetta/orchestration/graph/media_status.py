"""Typed per-turn media outcome shared by TTS and performance delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class MediaStatus:
    status: Literal["ready", "degraded", "skipped"]
    reason: str | None = None
    provider: str | None = None
    retryable: bool = False
