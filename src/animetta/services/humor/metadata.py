"""Metadata handoff helpers for graph-visible Humor Agent nodes."""

from __future__ import annotations

from typing import Any

from .models import HumorRewriteResult

HUMOR_AGENT_KEY = "humor_agent"
HUMOR_CANDIDATE_KEY = "humor_candidate"
HUMOR_VALIDATION_KEY = "humor_validation"


def _reason_value(reason: Any) -> str | None:
    if reason is None:
        return None
    return str(reason)


def candidate_to_metadata(result: HumorRewriteResult) -> dict[str, Any]:
    """Serialize the full internal candidate handoff."""
    return {
        "user_input": result.user_input,
        "normal_response": result.normal_response,
        "scene": result.scene,
        "emotion": result.emotion,
        "humor_anchor": result.humor_anchor,
        "worldview_mapping": result.worldview_mapping,
        "style": result.style,
        "candidate_response": result.candidate_response,
        "risk": result.risk,
        "accepted": result.accepted,
        "fallback_reason": _reason_value(result.fallback_reason),
        "enabled": result.enabled,
        "duration_ms": result.duration_ms,
    }


def candidate_from_metadata(metadata: dict[str, Any]) -> HumorRewriteResult | None:
    """Restore a candidate handoff from response metadata."""
    data = metadata.get(HUMOR_CANDIDATE_KEY)
    if not isinstance(data, dict):
        return None
    return HumorRewriteResult(
        user_input=str(data.get("user_input", "")),
        normal_response=str(data.get("normal_response", "")),
        scene=str(data.get("scene", "")),
        emotion=str(data.get("emotion", "")),
        humor_anchor=str(data.get("humor_anchor", "")),
        worldview_mapping=str(data.get("worldview_mapping", "")),
        style=str(data.get("style", "")),
        candidate_response=str(data.get("candidate_response", "")),
        risk=str(data.get("risk", "")),
        accepted=bool(data.get("accepted", False)),
        fallback_reason=data.get("fallback_reason"),
        enabled=bool(data.get("enabled", True)),
        duration_ms=float(data.get("duration_ms", 0.0) or 0.0),
    )


def record_humor_candidate(
    metadata: dict[str, Any],
    result: HumorRewriteResult,
) -> dict[str, Any]:
    """Return metadata with a full candidate handoff and compact diagnostics."""
    updated = {**metadata}
    updated[HUMOR_AGENT_KEY] = result.to_metadata()
    if result.candidate_response:
        updated[HUMOR_CANDIDATE_KEY] = candidate_to_metadata(result)
    else:
        updated.pop(HUMOR_CANDIDATE_KEY, None)
    return updated


def record_humor_validation(
    metadata: dict[str, Any],
    result: HumorRewriteResult,
) -> dict[str, Any]:
    """Return metadata with final validation diagnostics."""
    updated = {**metadata}
    compact = result.to_metadata()
    updated[HUMOR_AGENT_KEY] = compact
    updated[HUMOR_VALIDATION_KEY] = {
        "accepted": result.accepted,
        "fallback_reason": _reason_value(result.fallback_reason),
        "style": result.style,
        "risk": result.risk,
    }
    return updated
