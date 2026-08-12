from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from animetta.services.dialogue.sandbox import (
    SandboxConversationError,
    SandboxConversationService,
    SandboxTurn,
)
from animetta.services.llm.interface import LLMInterface


class NativeSandboxLLM(LLMInterface):
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def chat(self, user_input: str, **kwargs) -> str:
        raise AssertionError("sandbox must not use shared chat history")

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        return "unused"

    async def chat_messages_stream(
        self, messages: list[dict[str, str]], **kwargs
    ) -> AsyncIterator[str]:
        self.messages = messages
        yield "真实"
        yield "回复"

    def chat_stream(self, user_input: str, **kwargs) -> AsyncIterator[str]:
        raise AssertionError("sandbox must not use shared chat history")

    def set_system_prompt(self, prompt: str) -> None: ...

    def get_history(self) -> list[dict[str, str]]:
        return []

    def clear_history(self) -> None: ...

    async def close(self) -> None: ...

    def handle_interrupt(self, heard_response: str = "") -> None: ...

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None: ...


class HistoryUnsafeLLM(NativeSandboxLLM):
    chat_messages = LLMInterface.chat_messages


class EmptySandboxLLM(NativeSandboxLLM):
    async def chat_messages_stream(
        self, messages: list[dict[str, str]], **kwargs
    ) -> AsyncIterator[str]:
        if False:
            yield ""


async def test_sandbox_streams_explicit_history_without_public_pipeline() -> None:
    llm = NativeSandboxLLM()
    service = SandboxConversationService(llm)

    chunks = [
        chunk
        async for chunk in service.stream(
            "现在怎么样？",
            [SandboxTurn(role="user", content="记住这只在沙盒")],
            system_prompt="你是 Anima",
        )
    ]

    assert chunks == ["真实", "回复"]
    assert llm.messages == [
        {"role": "system", "content": "你是 Anima"},
        {"role": "user", "content": "记住这只在沙盒"},
        {"role": "user", "content": "现在怎么样？"},
    ]
    assert llm.get_history() == []


async def test_sandbox_rejects_provider_without_history_neutral_messages() -> None:
    service = SandboxConversationService(HistoryUnsafeLLM())

    with pytest.raises(SandboxConversationError, match="history_unsafe"):
        async for _ in service.stream("hello", system_prompt="private"):
            pass


async def test_sandbox_rejects_an_empty_provider_response() -> None:
    service = SandboxConversationService(EmptySandboxLLM())

    with pytest.raises(SandboxConversationError, match="empty_response"):
        async for _ in service.stream("hello", system_prompt="private"):
            pass
