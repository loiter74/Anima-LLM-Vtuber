"""Typed contracts for the Humor Agent pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .config import HumorConfig


class HumorFallbackReason(StrEnum):
    """Stable fallback and rejection reasons used by tests and diagnostics."""

    DISABLED = "disabled"
    NO_NORMAL_RESPONSE = "no_normal_response"
    HISTORY_UNSAFE = "history_unsafe"
    LLM_TIMEOUT = "llm_timeout"
    LLM_ERROR = "llm_error"
    INVALID_JSON = "invalid_json"
    MISSING_FIELD = "missing_field"
    EMPTY_CANDIDATE = "empty_candidate"
    CANDIDATE_TOO_LONG = "candidate_too_long"
    UNSAFE_RISK = "unsafe_risk"
    UNSAFE_CONTENT = "unsafe_content"
    HOSTILE_VIEWER_TARGETING = "hostile_viewer_targeting"
    CUSTOMER_SERVICE_PHRASE = "customer_service_phrase"
    STYLE_NOT_ALLOWED = "style_not_allowed"


@dataclass(slots=True)
class HumorRewriteRequest:
    """Input to the Humor Agent rewrite pipeline."""

    user_input: str
    normal_response: str
    persona: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    memory_context: str = ""
    config: HumorConfig = field(default_factory=HumorConfig)


@dataclass(slots=True)
class InternalLLMCallResult:
    """Result of a history-safe internal LLM call."""

    content: str | None = None
    fallback_reason: HumorFallbackReason | None = None


@dataclass(slots=True)
class HumorRewriteResult:
    """Structured output from the Humor Agent pipeline."""

    user_input: str
    normal_response: str
    scene: str = ""
    emotion: str = ""
    humor_anchor: str = ""
    worldview_mapping: str = ""
    style: str = ""
    candidate_response: str = ""
    risk: str = ""
    accepted: bool = False
    fallback_reason: HumorFallbackReason | str | None = None
    enabled: bool = True
    duration_ms: float = 0.0

    @property
    def visible_response(self) -> str:
        """Return the response that should be shown to viewers."""
        if self.accepted and self.candidate_response:
            return self.candidate_response
        return self.normal_response

    def reject(self, reason: HumorFallbackReason | str) -> HumorRewriteResult:
        """Mark the result as rejected with a stable reason."""
        self.accepted = False
        self.fallback_reason = reason
        return self

    def accept(self) -> HumorRewriteResult:
        """Mark the candidate as accepted."""
        self.accepted = True
        self.fallback_reason = None
        return self

    def to_metadata(self) -> dict[str, Any]:
        """Compact diagnostics safe for response metadata."""
        return {
            "enabled": self.enabled,
            "accepted": self.accepted,
            "fallback_reason": str(self.fallback_reason) if self.fallback_reason else None,
            "scene": self.scene,
            "emotion": self.emotion,
            "humor_anchor": self.humor_anchor,
            "worldview_mapping": self.worldview_mapping,
            "style": self.style,
            "risk": self.risk,
            "duration_ms": round(self.duration_ms, 2),
        }


def fallback_result(
    request: HumorRewriteRequest,
    reason: HumorFallbackReason | str,
    *,
    duration_ms: float = 0.0,
    enabled: bool = True,
) -> HumorRewriteResult:
    """Create a structured fallback result that preserves the normal response."""
    return HumorRewriteResult(
        user_input=request.user_input,
        normal_response=request.normal_response,
        accepted=False,
        fallback_reason=reason,
        enabled=enabled,
        duration_ms=duration_ms,
    )
