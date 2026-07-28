"""Bounded semantic performance plans for Live2D responses."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal, cast

PerformanceBase = Literal["calm", "annoyed", "surprised"]
PerformanceIntensity = Literal["subtle", "medium"]
PerformanceAccent = Literal["none"]
PerformanceSource = Literal["llm", "legacy", "fallback"]

PERFORMANCE_BASES: tuple[PerformanceBase, ...] = ("calm", "annoyed", "surprised")
PERFORMANCE_INTENSITIES: tuple[PerformanceIntensity, ...] = ("subtle", "medium")
PERFORMANCE_ACCENTS: tuple[PerformanceAccent, ...] = ("none",)
_DEPRECATED_BASES: dict[str, PerformanceBase] = {
    "cheerful": "calm",
    "concerned": "annoyed",
    "thinking": "calm",
    "smug": "calm",
}
_DEPRECATED_ACCENTS: dict[str, PerformanceAccent] = {
    "brighten": "none",
    "skeptical": "none",
    "startle": "none",
    "sigh": "none",
}

_PERFORMANCE_MARKER_SHAPE_RE = re.compile(r"\[live2d:[^\]\r\n]*\]", re.IGNORECASE)
_LEADING_PERFORMANCE_MARKER_RE = re.compile(
    r"^\s*\[live2d:"
    r"(?P<base>calm|cheerful|concerned|annoyed|surprised|thinking|smug)"
    r"\|(?P<intensity>subtle|medium)"
    r"\|(?P<accent>none|brighten|skeptical|startle|sigh)"
    r"\]",
    re.IGNORECASE,
)
_LEGACY_EMOTIONS = ("happy", "sad", "angry", "surprised", "neutral", "thinking")
_LEGACY_MARKER_RE = re.compile(
    rf"\[(?P<emotion>{'|'.join(_LEGACY_EMOTIONS)})\]",
    re.IGNORECASE,
)

_BASE_TO_EMOTION: dict[str, str] = {
    "calm": "neutral",
    "cheerful": "happy",
    "concerned": "sad",
    "annoyed": "angry",
    "surprised": "surprised",
    "thinking": "thinking",
    "smug": "neutral",
}
_LEGACY_TO_BASE: dict[str, PerformanceBase] = {
    "happy": "calm",
    "sad": "annoyed",
    "angry": "annoyed",
    "surprised": "surprised",
    "neutral": "calm",
    "thinking": "calm",
}


@dataclass(frozen=True, slots=True)
class Live2DPerformancePlan:
    """Version-one semantic plan safe to send to the renderer."""

    version: Literal[1]
    base: PerformanceBase
    intensity: PerformanceIntensity
    accent: PerformanceAccent
    source: PerformanceSource

    def to_dict(self) -> dict[str, object]:
        """Return the bounded wire representation."""

        return asdict(self)


CALM_PERFORMANCE_PLAN = Live2DPerformancePlan(
    version=1,
    base="calm",
    intensity="subtle",
    accent="none",
    source="fallback",
)


@dataclass(frozen=True, slots=True)
class PerformanceParseResult:
    """Normalized plan and content-safe text from one LLM response."""

    plan: Live2DPerformancePlan
    cleaned_text: str
    compatible_emotion: str
    fallback_reason: Literal["missing_marker", "invalid_marker"] | None = None


def parse_performance_plan(text: str) -> PerformanceParseResult:
    """Parse one bounded marker, migrate legacy tags, and strip all marker text."""

    raw_text = text or ""
    leading = _LEADING_PERFORMANCE_MARKER_RE.match(raw_text)
    legacy = _LEGACY_MARKER_RE.search(raw_text)

    if leading is not None:
        raw_base = leading.group("base").lower()
        intensity = leading.group("intensity").lower()
        raw_accent = leading.group("accent").lower()
        base = _DEPRECATED_BASES.get(raw_base, cast(PerformanceBase, raw_base))
        accent = _DEPRECATED_ACCENTS.get(raw_accent, cast(PerformanceAccent, raw_accent))
        source: PerformanceSource = "legacy" if base != raw_base or accent != raw_accent else "llm"
        plan = Live2DPerformancePlan(
            version=1,
            base=base,
            intensity=cast(PerformanceIntensity, intensity),
            accent=accent,
            source=source,
        )
        compatible_emotion = _BASE_TO_EMOTION[raw_base]
        fallback_reason: Literal["missing_marker", "invalid_marker"] | None = None
    elif legacy is not None:
        emotion = legacy.group("emotion").lower()
        plan = Live2DPerformancePlan(
            version=1,
            base=_LEGACY_TO_BASE[emotion],
            intensity="subtle",
            accent="none",
            source="legacy",
        )
        compatible_emotion = emotion
        fallback_reason = None
    else:
        plan = CALM_PERFORMANCE_PLAN
        compatible_emotion = _BASE_TO_EMOTION[plan.base]
        fallback_reason = (
            "invalid_marker" if _PERFORMANCE_MARKER_SHAPE_RE.search(raw_text) else "missing_marker"
        )

    cleaned_text = _PERFORMANCE_MARKER_SHAPE_RE.sub("", raw_text)
    cleaned_text = _LEGACY_MARKER_RE.sub("", cleaned_text)
    cleaned_text = re.sub(r"[ \t]{2,}", " ", cleaned_text).strip()

    return PerformanceParseResult(
        plan=plan,
        cleaned_text=cleaned_text,
        compatible_emotion=compatible_emotion,
        fallback_reason=fallback_reason,
    )


def validated_performance_payload(value: object) -> dict[str, object] | None:
    """Return a canonical bounded wire payload or reject the whole value."""

    if not isinstance(value, dict) or set(value) != {
        "version",
        "base",
        "intensity",
        "accent",
        "source",
    }:
        return None
    if value.get("version") != 1:
        return None
    base = value.get("base")
    intensity = value.get("intensity")
    accent = value.get("accent")
    source = value.get("source")
    if intensity not in PERFORMANCE_INTENSITIES or source not in {
        "llm",
        "legacy",
        "fallback",
    }:
        return None
    normalized_base = _DEPRECATED_BASES.get(str(base), cast(PerformanceBase, base))
    normalized_accent = _DEPRECATED_ACCENTS.get(str(accent), cast(PerformanceAccent, accent))
    if normalized_base not in PERFORMANCE_BASES or normalized_accent not in PERFORMANCE_ACCENTS:
        return None
    normalized_source = (
        "legacy" if normalized_base != base or normalized_accent != accent else source
    )
    return {
        "version": 1,
        "base": normalized_base,
        "intensity": intensity,
        "accent": normalized_accent,
        "source": normalized_source,
    }
