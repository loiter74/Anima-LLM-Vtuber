"""Central content-free persistence authorization for dialogue data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PersistenceMode = Literal["off", "read_only", "read_write"]
PersistenceSink = Literal[
    "session_window", "stats_metadata", "stats_content", "checkpoint",
    "long_term_recall", "long_term_write", "compatibility_callback",
]
ContentClass = Literal[
    "selected_final", "outcome_metadata", "query", "probe", "mock",
    "static_template", "internal_prompt", "reasoner", "translation",
    "rejected_candidate", "incomplete",
]

_FORBIDDEN = {
    "probe", "mock", "static_template", "internal_prompt", "reasoner",
    "translation", "rejected_candidate", "incomplete",
}


@dataclass(frozen=True, slots=True)
class PersistenceRequest:
    mode: PersistenceMode
    sink: PersistenceSink
    content_class: ContentClass
    completed: bool
    real_provider: bool


@dataclass(frozen=True, slots=True)
class PersistenceDecision:
    allowed: bool
    reason: str


def decide_persistence(request: PersistenceRequest) -> PersistenceDecision:
    if request.content_class in _FORBIDDEN:
        return PersistenceDecision(
            False, f"content_class_forbidden:{request.content_class}"
        )
    if request.sink == "stats_metadata" and request.content_class == "outcome_metadata":
        return PersistenceDecision(True, "metadata_allowlist")
    if request.sink == "session_window":
        allowed = (
            request.content_class == "selected_final"
            and request.completed
            and request.real_provider
        )
        return PersistenceDecision(allowed, "selected_final" if allowed else "turn_ineligible")
    if request.sink in {"stats_content", "checkpoint"}:
        return PersistenceDecision(False, "content_sink_disabled")
    if request.sink == "long_term_recall":
        allowed = request.mode in {"read_only", "read_write"}
        return PersistenceDecision(allowed, "mode_allows_recall" if allowed else "mode_off")
    if request.sink in {"long_term_write", "compatibility_callback"}:
        if request.mode != "read_write":
            return PersistenceDecision(False, f"mode_{request.mode}")
        allowed = (
            request.content_class == "selected_final"
            and request.completed
            and request.real_provider
        )
        return PersistenceDecision(allowed, "selected_final" if allowed else "turn_ineligible")
    return PersistenceDecision(False, "sink_unknown")
