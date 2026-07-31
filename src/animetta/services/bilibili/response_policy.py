"""Delivery-safe response policy for live audience interactions."""

from __future__ import annotations

LIVESTREAM_REPLY_MAX_CHARS = 18
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
