"""Factory-closed contract for explicit, history-neutral LLM calls."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from importlib import import_module
from importlib.machinery import ModuleSpec
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import torch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from animetta.orchestration.graph.conversation_session import ConversationSessionState
from animetta.orchestration.graph.llm_node import (
    _explicit_history_messages,
    _provider_message,
)
from animetta.services.llm.factory import LLMFactory
from animetta.services.llm.glm_llm import GLMLLM
from animetta.services.llm.local_lora_llm import LocalLoraLLM
from animetta.services.llm.mock_llm import MockLLM
from animetta.services.llm.openai_llm import OpenAILLM

ProviderBuilder = Callable[[], tuple[Any, list[list[dict]]]]


class _AsyncChunks:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        for chunk in self._chunks:
            yield chunk


def _openai(provider_identity: str) -> tuple[OpenAILLM, list[list[dict]]]:
    captured: list[list[dict]] = []

    async def create(**kwargs):
        captured.append([dict(message) for message in kwargs["messages"]])
        if kwargs.get("stream"):
            return _AsyncChunks(
                [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))])]
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    instance = object.__new__(OpenAILLM)
    instance.model = "contract-model"
    instance.temperature = 0.1
    instance.top_p = 0.9
    instance.max_tokens = 32
    instance.extra_body = {}
    instance.history = [{"role": "assistant", "content": "shared-sentinel"}]
    instance._provider_identity = provider_identity
    instance.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return instance, captured


def _glm() -> tuple[GLMLLM, list[list[dict]]]:
    captured: list[list[dict]] = []

    def create(**kwargs):
        captured.append([dict(message) for message in kwargs["messages"]])
        if kwargs.get("stream"):
            return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))])]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )

    instance = object.__new__(GLMLLM)
    instance.config = SimpleNamespace(model="glm-contract", temperature=0.1)
    instance.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    instance._conversation_history = [{"role": "assistant", "content": "shared-sentinel"}]
    instance._call_count = 0
    instance._total_input_tokens = 0
    instance._total_output_tokens = 0
    return instance, captured


def _ollama() -> tuple[Any, list[list[dict]]]:
    try:
        module = import_module("animetta.services.llm.ollama_llm")
    except ModuleNotFoundError as exc:
        if exc.name != "ollama":
            raise
        dependency = ModuleType("ollama")
        dependency.__spec__ = ModuleSpec("ollama", loader=None)
        dependency.Client = object  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"ollama": dependency}):
            module = import_module("animetta.services.llm.ollama_llm")
    ollama_llm = module.OllamaLLM
    captured: list[list[dict]] = []

    def chat(**kwargs):
        captured.append([dict(message) for message in kwargs["messages"]])
        if kwargs.get("stream"):
            return [{"message": {"content": "ok"}}]
        return {"message": {"content": "ok"}}

    instance = object.__new__(ollama_llm)
    instance.model = "ollama-contract"
    instance.temperature = 0.1
    instance.max_tokens = 32
    instance.history = [{"role": "assistant", "content": "shared-sentinel"}]
    instance.client = SimpleNamespace(chat=chat)
    return instance, captured


class _TokenBatch(dict):
    def to(self, device: str) -> _TokenBatch:
        del device
        return self


class _Tokenizer:
    pad_token_id = 0
    eos_token_id = 2

    def __init__(self, captured: list[list[dict]]) -> None:
        self.captured = captured

    def apply_chat_template(self, messages: list[dict], **kwargs) -> str:
        del kwargs
        self.captured.append([dict(message) for message in messages])
        return "contract prompt"

    def __call__(self, prompt: str, **kwargs) -> _TokenBatch:
        del prompt, kwargs
        return _TokenBatch(input_ids=torch.tensor([[1, 2]]))

    def decode(self, tokens: Any, **kwargs) -> str:
        del tokens, kwargs
        return "ok"


def _local_lora() -> tuple[LocalLoraLLM, list[list[dict]]]:
    captured: list[list[dict]] = []
    instance = object.__new__(LocalLoraLLM)
    instance._loaded = True
    instance.device = "cpu"
    instance.tokenizer = _Tokenizer(captured)
    instance.model = SimpleNamespace(generate=lambda **kwargs: torch.tensor([[1, 2, 3]]))
    instance.history = [{"role": "assistant", "content": "shared-sentinel"}]
    return instance, captured


class _RecordingMock(MockLLM):
    def __init__(self, captured: list[list[dict]]) -> None:
        super().__init__()
        self._captured = captured

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        self._captured.append([dict(message) for message in messages])
        return await super().chat_messages(messages, **kwargs)


def _mock() -> tuple[MockLLM, list[list[dict]]]:
    captured: list[list[dict]] = []
    instance = _RecordingMock(captured)
    instance.history = [{"role": "assistant", "content": "shared-sentinel"}]
    return instance, captured


PROVIDER_ADAPTERS: dict[str, ProviderBuilder] = {
    "mock": _mock,
    "glm": _glm,
    "ollama": _ollama,
    "openai": lambda: _openai("openai"),
    "deepseek": lambda: _openai("deepseek"),
    "local_lora": _local_lora,
}


def test_provider_contract_matrix_is_closed_over_factory_catalog() -> None:
    assert set(PROVIDER_ADAPTERS) == set(LLMFactory.get_available_configs())


@pytest.mark.parametrize("provider_name", PROVIDER_ADAPTERS, ids=PROVIDER_ADAPTERS)
async def test_explicit_messages_preserve_order_and_shared_history(
    provider_name: str,
) -> None:
    provider, captured = PROVIDER_ADAPTERS[provider_name]()
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old-user"},
        {"role": "assistant", "content": "old-assistant"},
        {"role": "user", "content": "current-user"},
    ]
    history_attr = "_conversation_history" if provider_name == "glm" else "history"
    before = [dict(message) for message in getattr(provider, history_attr)]

    response = await provider.chat_messages(messages)
    streamed = "".join([chunk async for chunk in provider.chat_messages_stream(messages)])

    assert response
    assert streamed
    assert captured == [messages, messages]
    assert getattr(provider, history_attr) == before
    if provider_name == "deepseek":
        assert provider.provider_identity == "deepseek"


def test_tool_chain_follows_current_user_without_duplication() -> None:
    session = ConversationSessionState()
    session.commit(
        task_id="previous",
        user_text="previous-user",
        final_response="previous-assistant",
    )
    current = HumanMessage(content="current-user")
    assistant = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "lookup", "args": {"q": "x"}}],
    )
    tool = ToolMessage(content="tool-result", tool_call_id="call-1")

    ordered = _explicit_history_messages(
        [current, assistant, tool],
        {"max_context_tokens": 6000},
        {"configurable": {"conversation_session": session}},
        "contract",
    )
    provider_messages = [_provider_message(message) for message in ordered]

    assert [message["role"] for message in provider_messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "tool",
    ]
    assert sum(message.get("content") == "current-user" for message in provider_messages) == 1
