"""Bounded semantic performance plans for Live2D responses."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal, cast

PerformanceBase = Literal[
    "calm",
    "cheerful",
    "concerned",
    "annoyed",
    "surprised",
    "thinking",
    "smug",
]
PerformanceIntensity = Literal["subtle", "medium"]
PerformanceAccent = Literal["none", "brighten", "skeptical", "startle", "sigh"]
PerformanceSource = Literal["llm", "legacy", "fallback"]

PERFORMANCE_BASES = frozenset(
    {"calm", "cheerful", "concerned", "annoyed", "surprised", "thinking", "smug"}
)
PERFORMANCE_INTENSITIES = frozenset({"subtle", "medium"})
PERFORMANCE_ACCENTS = frozenset({"none", "brighten", "skeptical", "startle", "sigh"})

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
    "happy": "cheerful",
    "sad": "concerned",
    "angry": "annoyed",
    "surprised": "surprised",
    "neutral": "calm",
    "thinking": "thinking",
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
        base = leading.group("base").lower()
        intensity = leading.group("intensity").lower()
        accent = leading.group("accent").lower()
        plan = Live2DPerformancePlan(
            version=1,
            base=cast(PerformanceBase, base),
            intensity=cast(PerformanceIntensity, intensity),
            accent=cast(PerformanceAccent, accent),
            source="llm",
        )
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
        fallback_reason = None
    else:
        plan = CALM_PERFORMANCE_PLAN
        fallback_reason = (
            "invalid_marker" if _PERFORMANCE_MARKER_SHAPE_RE.search(raw_text) else "missing_marker"
        )

    cleaned_text = _PERFORMANCE_MARKER_SHAPE_RE.sub("", raw_text)
    cleaned_text = _LEGACY_MARKER_RE.sub("", cleaned_text)
    cleaned_text = re.sub(r"[ \t]{2,}", " ", cleaned_text).strip()

    return PerformanceParseResult(
        plan=plan,
        cleaned_text=cleaned_text,
        compatible_emotion=_BASE_TO_EMOTION[plan.base],
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
    if (
        base not in PERFORMANCE_BASES
        or intensity not in PERFORMANCE_INTENSITIES
        or accent not in PERFORMANCE_ACCENTS
        or source not in {"llm", "legacy", "fallback"}
    ):
        return None
    return {
        "version": 1,
        "base": base,
        "intensity": intensity,
        "accent": accent,
        "source": source,
    }
