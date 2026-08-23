"""History-neutral helpers for internal LLM calls."""

from __future__ import annotations

from typing import Any

from animetta.observability.service_proxy import unwrap_service_proxy as _unwrap_service_proxy

from .interface import LLMInterface


class HistoryUnsafeLLMError(RuntimeError):
    """Raised when an internal call would fall back to shared chat history."""


def unwrap_service_proxy(service: object) -> object:
    """Return the wrapped service when a tracing proxy is supplied."""
    return _unwrap_service_proxy(service)


def has_native_chat_messages(llm: object) -> bool:
    """Return whether the concrete provider implements stateless messages calls."""
    target = unwrap_service_proxy(llm)
    implementation = getattr(type(target), "chat_messages", None)
    return implementation is not None and implementation is not LLMInterface.chat_messages


async def call_native_chat_messages(
    llm: LLMInterface,
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> str:
    """Call a provider-native messages API without a history-mutating fallback."""
    if not has_native_chat_messages(llm):
        raise HistoryUnsafeLLMError("provider does not implement native chat_messages")
    return await llm.chat_messages(messages, **kwargs)
