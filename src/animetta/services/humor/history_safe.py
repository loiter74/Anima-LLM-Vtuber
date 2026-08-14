"""History-safe internal LLM calls for non-user-facing transformations."""

from __future__ import annotations

from loguru import logger

from animetta.services.llm.interface import LLMInterface
from animetta.services.llm.internal_calls import (
    has_native_chat_messages,
)

from .models import HumorFallbackReason, InternalLLMCallResult


async def chat_messages_history_safe(
    llm: LLMInterface,
    messages: list[dict[str, str]],
) -> InternalLLMCallResult:
    """Call chat_messages without leaking internal prompts into chat history."""
    if has_native_chat_messages(llm):
        content = await llm.chat_messages(messages)
        return InternalLLMCallResult(content=content)

    logger.warning("[HumorAgent] Provider lacks history-neutral chat_messages")
    return InternalLLMCallResult(fallback_reason=HumorFallbackReason.HISTORY_UNSAFE)
