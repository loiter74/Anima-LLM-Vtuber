"""Delivery helpers: apply CompiledPrompt to tool-calling and streaming paths."""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from .types import CompiledPrompt


def apply_to_messages(compiled: CompiledPrompt, messages: list) -> list:
    """Insert compiled system prompt as the first message (streaming mode).

    If messages already starts with a SystemMessage, replaces it.
    Otherwise inserts at position 0.
    """
    if not compiled.system_prompt:
        return messages
    if messages and isinstance(messages[0], SystemMessage):
        messages[0] = SystemMessage(content=compiled.system_prompt)
    else:
        messages.insert(0, SystemMessage(content=compiled.system_prompt))
    return messages
