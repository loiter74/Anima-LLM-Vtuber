"""Classify English provider meta-reasoning without transport dependencies."""

from __future__ import annotations

import re

_UNAMBIGUOUS_META_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:"
    r"the user\s+(?:just\s+)?(?:says|said|asks|asked|wants|is)\b|"
    r"user\s+(?:says|said|asks|asked|wants|is)\b|"
    r"according to (?:my|the) (?:instructions|system prompt)\b"
    r")"
)
_AMBIGUOUS_PLANNING_PREFIX_RE = re.compile(r"(?is)^\s*(?:i (?:should|need to|have to)\b|let me\b)")
_META_CONTEXT_RE = re.compile(
    r"(?is)\b(?:"
    r"(?:the\s+)?user(?:'s)?\s+(?:request|message|question|prompt|instructions?)|"
    r"(?:system\s+)?prompt|instructions?|persona|in character|"
    r"current affinity|need to include|what to say|step[ -]by[ -]step|"
    r"(?:my|the|a|an)\s+(?:response|reply|answer)|emotion tags?"
    r")\b"
)
_PLANNING_ACTION_RE = re.compile(
    r"(?is)\b(?:"
    r"analy[sz]e|reason|decide|determine|formulate|craft|compose|generate|"
    r"respond|reply|answer|think through|work out|plan|figure out|consider|"
    r"evaluate|include|use"
    r")\b"
)


def is_english_meta_reasoning(text: str) -> bool:
    """Return true only for English planning about how to answer the user."""
    if _UNAMBIGUOUS_META_PREFIX_RE.match(text):
        return True
    if not _AMBIGUOUS_PLANNING_PREFIX_RE.match(text):
        return False
    return bool(_META_CONTEXT_RE.search(text) and _PLANNING_ACTION_RE.search(text))


__all__ = ["is_english_meta_reasoning"]
