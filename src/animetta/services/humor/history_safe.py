"""History-safe internal LLM calls for non-user-facing transformations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from loguru import logger

from animetta.services.llm.interface import LLMInterface

from .models import HumorFallbackReason, InternalLLMCallResult

_HISTORY_ATTRS = ("history", "_history", "_conversation_history")


def unwrap_service_proxy(service: object) -> object:
    """Return the wrapped service object when a tracing proxy is supplied."""
    try:
        return object.__getattribute__(service, "_target")
    except AttributeError:
        return service


def has_native_chat_messages(llm: object) -> bool:
    """Return True when the concrete LLM overrides LLMInterface.chat_messages."""
    target = unwrap_service_proxy(llm)
    return (
        hasattr(type(target), "chat_messages")
        and type(target).chat_messages is not LLMInterface.chat_messages
    )


def _copy_history(history: Sequence[Any]) -> list[Any]:
    copied = []
    for msg in history:
        copied.append(msg.copy() if isinstance(msg, dict) else msg)
    return copied


def _history_storage(target: object) -> list[Any] | None:
    for attr in _HISTORY_ATTRS:
        try:
            value = object.__getattribute__(target, attr)
        except AttributeError:
            continue
        if isinstance(value, list):
            return value
    return None


def _can_restore_history(target: object) -> tuple[bool, list[Any]]:
    if not hasattr(target, "get_history") or not hasattr(target, "clear_history"):
        return False, []
    storage = _history_storage(target)
    if storage is None:
        return False, []
    try:
        snapshot = target.get_history()
    except Exception:
        return False, []
    if not isinstance(snapshot, list):
        return False, []
    return True, _copy_history(snapshot)


def restore_history(target: object, snapshot: list[Any]) -> bool:
    """Restore provider-local history to a previous snapshot when possible."""
    storage = _history_storage(target)
    if storage is None or not hasattr(target, "clear_history"):
        return False
    try:
        target.clear_history()
        storage.extend(_copy_history(snapshot))
        return True
    except Exception as exc:
        logger.error(f"[HumorAgent] Failed to restore LLM history: {exc}")
        return False


async def chat_messages_history_safe(
    llm: LLMInterface,
    messages: list[dict[str, str]],
) -> InternalLLMCallResult:
    """Call chat_messages without leaking internal prompts into chat history."""
    target = unwrap_service_proxy(llm)

    if has_native_chat_messages(target):
        content = await llm.chat_messages(messages)
        return InternalLLMCallResult(content=content)

    can_restore, snapshot = _can_restore_history(target)
    if not can_restore:
        logger.warning("[HumorAgent] Cannot safely call LLM; history restoration unavailable")
        return InternalLLMCallResult(fallback_reason=HumorFallbackReason.HISTORY_UNSAFE)

    try:
        content = await llm.chat_messages(messages)
        return InternalLLMCallResult(content=content)
    finally:
        restore_history(target, snapshot)


def replace_last_assistant_history(
    llm: object,
    original_response: str,
    final_response: str,
) -> bool:
    """Replace the last provider-local assistant message with the visible reply."""
    target = unwrap_service_proxy(llm)
    storage = _history_storage(target)
    if storage is None:
        return False

    for msg in reversed(storage):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        if msg.get("content") == original_response or not msg.get("content"):
            msg["content"] = final_response
            return True
        # If the last assistant differs, avoid rewriting older history.
        return False
    return False

