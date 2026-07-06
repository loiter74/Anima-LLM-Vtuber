"""Ingress filtering for chat messages.

Centralizes the "is this a real user message?" decision so the LLM pipeline,
memory storage, and inspection scheduler all agree on what counts as a probe.

This is the first line of defense against the "历史串台虫" (history bleed bug):
inspection pings, health probes, and other non-conversational payloads must
never reach the LLM or be persisted as conversation history.

Design rules:
- Pure functions only — no I/O, no logging side effects beyond debug.
- Conservative: when uncertain, return False (let real chat through).
- Symmetric: a probe flagged by ``is_inspection_probe`` or detected by
  ``should_skip_llm`` is treated identically by callers.
"""

from __future__ import annotations

from typing import Any

# ── Textual probes ────────────────────────────────────────────────────

# Prefixes that mark a payload as an internal probe, not a real danmaku.
_PROBE_PREFIXES: tuple[str, ...] = (
    "[inspection]",
    "[health]",
    "[probe]",
    "[system]",
)

# Bare tokens that, on their own, are clearly health checks rather than
# conversational turns. Compared case-insensitively against the stripped text.
_PROBE_TOKENS: frozenset[str] = frozenset({
    "ping",
    "pong",
    "healthcheck",
    "health-check",
    "heartbeat",
})

# Substrings that signal prompt-injection / context-bleed attempts. These are
# NOT used to skip the LLM (we still want Anima to respond in character), but
# callers may use them for telemetry. Kept here so the filter is the single
# source of truth for "what does a probe look like?".
BLEED_MARKERS: tuple[str, ...] = (
    "tell me about 用户:",
    "tell me about 助手:",
    "用户: ",
    "助手: ",
    "[inspection]",
)


def should_skip_llm(text: str) -> bool:
    """Return True when ``text`` is a probe and should NOT reach the LLM.

    Detection is purely textual:
    - The stripped text starts with one of ``_PROBE_PREFIXES``.
    - The stripped lowercased text is exactly one of ``_PROBE_TOKENS``.

    Empty/whitespace-only input also returns True — there is nothing to say.

    Args:
        text: Raw user-supplied text (already extracted from the payload).

    Returns:
        True if the message must be dropped before LLM dispatch.
    """
    if not text:
        return True

    stripped = text.strip()
    if not stripped:
        return True

    lowered = stripped.lower()

    if any(stripped.startswith(prefix) for prefix in _PROBE_PREFIXES):
        return True

    return lowered in _PROBE_TOKENS


def is_inspection_probe(data: dict[str, Any]) -> bool:
    """Return True when the Socket.IO payload explicitly flags itself as a probe.

    Recognized markers (any one suffices):
    - ``data["is_inspection"] is True``
    - ``data["is_probe"] is True`` (alias)
    - ``data["mode"] == "inspection"``

    Args:
        data: The raw payload dict received on the ``chat:text`` event.

    Returns:
        True if the payload self-identifies as an inspection/health probe.
    """
    if not isinstance(data, dict):
        return False

    if data.get("is_inspection") is True:
        return True

    if data.get("is_probe") is True:
        return True

    return data.get("mode") == "inspection"


def is_probe_message(data: dict[str, Any]) -> bool:
    """Combined check: payload-flagged OR text-shaped probe.

    This is the canonical entry point for ingress handlers — call this once
    at the top of ``on_text_input`` and short-circuit when it returns True.

    Args:
        data: The raw payload dict received on the ``chat:text`` event.

    Returns:
        True if the message should be dropped before orchestrator dispatch.
    """
    if is_inspection_probe(data):
        return True

    text = data.get("text", "")
    return isinstance(text, str) and should_skip_llm(text)
