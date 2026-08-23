"""Compatibility imports for dialogue roleplay drift detection."""

from animetta.services.dialogue.roleplay_guard import (
    CORRECTION_SECTION,
    FORBIDDEN_META_PATTERNS,
    FORBIDDEN_PHRASES,
    detect_drift,
    has_drift,
)

__all__ = [
    "CORRECTION_SECTION",
    "FORBIDDEN_META_PATTERNS",
    "FORBIDDEN_PHRASES",
    "detect_drift",
    "has_drift",
]
