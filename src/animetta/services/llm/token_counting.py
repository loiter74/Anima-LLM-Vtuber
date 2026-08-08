"""Token-counting utilities for context-budget trimming.

tiktoken is already a project dependency (preloaded at ``service_context.py`` to
warm the cache) but was never used to actually count tokens. This module wraps
it so ``llm_node`` can apply a token budget to the LangGraph ``messages`` state
via ``langchain_core.messages.trim_messages``.

Design notes:
- Falls back to ``cl100k_base`` when the model's encoding is unknown (safe
  over-estimate for most modern chat models).
- Accepts both ``langchain_core.messages.BaseMessage`` instances and plain dicts
  (``{"role": ..., "content": ...}``), since the graph mixes both shapes.
- All functions are synchronous and cheap (microsecond-scale); they run on the
  hot path inside ``llm_node``.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any, Protocol

_DEFAULT_ENCODING = "cl100k_base"


class _TokenizerLike(Protocol):
    def encode(self, text: str) -> list[int]: ...


@lru_cache(maxsize=16)
def _get_encoding(model: str | None) -> _TokenizerLike:
    """Return a tiktoken encoding for the model, falling back to cl100k_base.

    Cached so repeated calls in the hot path don't re-resolve the encoding.
    """
    import tiktoken

    try:
        return tiktoken.encoding_for_model(model or "")
    except (KeyError, ValueError):
        return tiktoken.get_encoding(_DEFAULT_ENCODING)


def _extract_text(message: Any) -> str:
    """Extract the textual content from a langchain message or plain dict."""
    # langchain BaseMessage exposes .content
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, list):
        # Multimodal content blocks: concatenate text parts.
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return " ".join(parts)
    return str(content or "")


def count_message_tokens(messages: list[Any], model: str | None = None) -> int:
    """Count the total tokens across a list of messages.

    Uses a per-message overhead of 4 tokens (role + framing), which is the
    standard approximation used by OpenAI's token calculator. This is a
    conservative over-estimate, which is the safe direction for budget trimming.
    """
    if not messages:
        return 0
    encoder = _get_encoding(model)
    total = 0
    for message in messages:
        text = _extract_text(message)
        total += len(encoder.encode(text)) + 4  # 4-token framing overhead per message
    return total


def make_trim_token_counter(model: str | None = None) -> Callable[[list[Any]], int]:
    """Build a ``token_counter`` callable for ``langchain trim_messages``.

    ``trim_messages`` expects a callable of signature ``(messages) -> int``.
    """

    def counter(messages: list[Any]) -> int:
        return count_message_tokens(messages, model=model)

    return counter
