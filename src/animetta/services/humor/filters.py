"""Deterministic safety and quality filters for Humor Agent candidates."""

from __future__ import annotations

import re

from .config import HumorConfig
from .models import HumorFallbackReason, HumorRewriteResult

_SAFE_RISKS = {"safe", "low", "low_risk", "ok"}

_UNSAFE_CONTENT_RE = re.compile(
    "|".join(
        [
            r"\bhate\s+speech\b",
            r"\bkill\s+yourself\b",
            r"\bsuicide\b",
            r"\brape\b",
            r"\bgenocide\b",
            r"\bslur\b",
            "仇恨",
            "歧视",
            "强奸",
            "自杀",
            "去死",
            "灭绝",
            "血腥暴力",
            "色情",
        ]
    ),
    re.IGNORECASE,
)

_HOSTILE_VIEWER_RE = re.compile(
    r"(你|观众|viewer|user).{0,8}(废物|垃圾|蠢|傻|闭嘴|滚|idiot|stupid|trash)",
    re.IGNORECASE,
)

_CUSTOMER_SERVICE_RE = re.compile(
    "|".join(
        [
            "作为一个AI",
            "作为 AI",
            "很抱歉",
            "非常抱歉",
            "请问还有什么可以帮",
            "希望这能帮助",
            "如果你还有其他问题",
            r"\bas an ai\b",
            r"\bi am sorry\b",
            r"\bhow can i help\b",
        ]
    ),
    re.IGNORECASE,
)


def _normalized_style(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _style_allowed(style: str, allowed_styles: list[str]) -> bool:
    if not allowed_styles:
        return True
    normalized = _normalized_style(style)
    allowed = [_normalized_style(item) for item in allowed_styles]
    return any(item and item in normalized for item in allowed)


def validate_humor_candidate(
    result: HumorRewriteResult,
    config: HumorConfig,
) -> HumorFallbackReason | None:
    """Return a stable rejection reason, or None when the candidate is valid."""
    candidate = (result.candidate_response or "").strip()
    if not candidate:
        return HumorFallbackReason.EMPTY_CANDIDATE
    if len(candidate) > config.max_candidate_chars:
        return HumorFallbackReason.CANDIDATE_TOO_LONG

    risk = (result.risk or "").strip().lower()
    if risk not in _SAFE_RISKS:
        return HumorFallbackReason.UNSAFE_RISK

    if _UNSAFE_CONTENT_RE.search(candidate):
        return HumorFallbackReason.UNSAFE_CONTENT
    if _HOSTILE_VIEWER_RE.search(candidate):
        return HumorFallbackReason.HOSTILE_VIEWER_TARGETING
    if _CUSTOMER_SERVICE_RE.search(candidate):
        return HumorFallbackReason.CUSTOMER_SERVICE_PHRASE
    if not _style_allowed(result.style, config.allowed_styles):
        return HumorFallbackReason.STYLE_NOT_ALLOWED

    return None
