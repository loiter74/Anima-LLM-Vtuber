"""Boundary validation helpers for cached scene guidance."""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from .models import SceneGuidance


def validate_scene_guidance(
    value: Any,
    *,
    now: float | None = None,
) -> tuple[SceneGuidance | None, list[str]]:
    """Validate untrusted turn metadata without exposing rejected content."""
    if value is None:
        return None, []
    try:
        guidance = SceneGuidance.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        return None, ["Scene guidance rejected: schema_invalid"]
    if guidance.is_expired(time.time() if now is None else now):
        return None, ["Scene guidance rejected: expired"]
    return guidance, []
