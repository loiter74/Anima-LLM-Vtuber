"""Delivery-safe response policy for live audience interactions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

LIVESTREAM_REPLY_MAX_CHARS = 18
PROACTIVE_TOPIC_REPLY_MAX_CHARS = 36
PROACTIVE_TOPIC_SOURCE = "bilibili:proactive_topic"
_SENTENCE_ENDINGS = frozenset("。！？!?")
_CLAUSE_ENDINGS = frozenset("，、；：,;:")


def constrain_livestream_response(
    text: str,
    *,
    max_chars: int = LIVESTREAM_REPLY_MAX_CHARS,
) -> str:
    """Return a complete, TTS-bounded livestream reply."""
    if max_chars < 2:
        raise ValueError("livestream response limit must be at least 2 characters")

    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized

    prefix = normalized[:max_chars]
    sentence_end = max((prefix.rfind(mark) for mark in _SENTENCE_ENDINGS), default=-1)
    if sentence_end >= 7:
        return prefix[: sentence_end + 1].strip()

    clause_end = max((prefix.rfind(mark) for mark in _CLAUSE_ENDINGS), default=-1)
    if clause_end >= 7:
        clause = prefix[:clause_end].rstrip("，、；：,;:…—- ")
        return f"{clause}。"
    if sentence_end >= 2:
        return prefix[: sentence_end + 1].strip()

    bounded = prefix[: max_chars - 1].rstrip("，、；：,;:…—- ")
    return f"{bounded}。"


def is_proactive_topic_turn(metadata: Mapping[str, Any] | None) -> bool:
    """Recognize the server-owned host source that may address the whole room."""
    return bool(
        isinstance(metadata, Mapping)
        and metadata.get("source") == PROACTIVE_TOPIC_SOURCE
        and metadata.get("actor_role") == "host"
        and metadata.get("audience") == "livestream"
    )


def constrain_proactive_topic_response(
    text: str,
    *,
    max_chars: int = PROACTIVE_TOPIC_REPLY_MAX_CHARS,
    recent_outputs: Sequence[str] = (),
) -> str:
    """Enforce one non-question sentence and reject exact recent repeats."""
    if max_chars > PROACTIVE_TOPIC_REPLY_MAX_CHARS:
        max_chars = PROACTIVE_TOPIC_REPLY_MAX_CHARS
    normalized = " ".join(text.split())
    if not normalized or "？" in normalized or "?" in normalized:
        return ""
    endings = [index for index, char in enumerate(normalized) if char in "。！!"]
    if endings:
        normalized = normalized[: endings[0] + 1]
    bounded = constrain_livestream_response(normalized, max_chars=max_chars)
    fingerprint = normalize_proactive_topic_text(bounded)
    if fingerprint and any(
        fingerprint == normalize_proactive_topic_text(previous) for previous in recent_outputs
    ):
        return ""
    return bounded


def normalize_proactive_topic_text(text: str) -> str:
    """Return the exact-repeat fingerprint used inside one livestream generation."""
    return "".join(text.split()).rstrip("。！？!?").casefold()
