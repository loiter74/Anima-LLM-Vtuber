from __future__ import annotations

"""Tests for provider history trimming (context-bloat guard).

The provider ``self.history`` lists are shared across sessions via ServicePool,
so they grow without bound unless trimmed. Each provider must bound history to
``max_history_messages`` after every append, using the shared
``LLMInterface._trim_history`` utility.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.services.llm.interface import LLMInterface
from animetta.services.llm.local_lora_llm import LocalLoraLLM
from animetta.services.llm.mock_llm import MockLLM
from animetta.services.llm.openai_llm import OpenAILLM

try:
    from animetta.services.llm.ollama_llm import OllamaLLM
except ModuleNotFoundError:
    OllamaLLM = None  # type: ignore[assignment,misc]


# ── The shared utility ────────────────────────────────────────────────────


class TestTrimHistoryUtility:
    def test_trims_to_last_n_entries(self) -> None:
        history = [{"role": "user", "content": str(i)} for i in range(10)]
        trimmed = LLMInterface._trim_history(history, 4)
        assert len(trimmed) == 4
        # Keeps the most recent entries.
        assert trimmed[-1]["content"] == "9"

    def test_no_trim_when_under_limit(self) -> None:
        history = [{"role": "user", "content": "hi"}]
        assert LLMInterface._trim_history(history, 20) == history

    def test_zero_disables_trimming(self) -> None:
        history = [{"role": "user", "content": str(i)} for i in range(100)]
        assert LLMInterface._trim_history(history, 0) == history

    def test_negative_disables_trimming(self) -> None:
        history = [{"role": "user", "content": "x"}]
        assert LLMInterface._trim_history(history, -1) == history


# ── MockLLM: deterministic, no external deps ──────────────────────────────


class TestMockLLMHistoryTrimming:
    @pytest.fixture(autouse=True)
    def _disable_simulated_processing_delay(self):
        with patch("asyncio.sleep", new=AsyncMock()):
            yield

    @pytest.mark.asyncio
    async def test_history_trims_to_max_after_many_turns(self) -> None:
        llm = MockLLM(max_history_messages=6)
        for i in range(20):
            await llm.chat(f"message {i}")
        assert len(llm.history) == 6
        # The most recent user message is preserved.
        assert "message 19" in llm.history[-2]["content"]

    @pytest.mark.asyncio
    async def test_history_does_not_trim_when_disabled(self) -> None:
        llm = MockLLM(max_history_messages=0)
        for i in range(15):
            await llm.chat(f"message {i}")
        assert len(llm.history) == 30  # 15 user + 15 assistant

    @pytest.mark.asyncio
    async def test_trim_preserves_recent_context(self) -> None:
        llm = MockLLM(max_history_messages=4)
        await llm.chat("oldest")
        await llm.chat("middle")
        await llm.chat("newest")
        # 3 turns = 6 messages, trimmed to 4 → oldest user msg evicted.
        assert len(llm.history) == 4
        contents = [msg["content"] for msg in llm.history]
        assert "oldest" not in contents
        assert "newest" in contents[-2] or "newest" in str(contents)

    def test_from_config_reads_max_history_messages(self) -> None:
        from animetta.config.providers.llm import MockLLMConfig

        config = MockLLMConfig(model="mock", max_history_messages=8)
        llm = MockLLM.from_config(config)
        assert llm.max_history_messages == 8

    def test_handle_interrupt_trims(self) -> None:
        llm = MockLLM(max_history_messages=4)
        llm.history = [{"role": "user", "content": f"u{i}"} for i in range(10)]
        llm.handle_interrupt("partial response")
        assert len(llm.history) == 4


# ── OpenAILLM: mocked AsyncOpenAI client ──────────────────────────────────


def _make_mock_openai_response(content: str = "ok") -> MagicMock:
    """Build a fake chat.completions.create response object."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return response


class TestOpenAILLMHistoryTrimming:
    @pytest.fixture(autouse=True)
    def _isolate_client_construction(self):
        with (
            patch("httpx.AsyncClient"),
            patch("animetta.services.llm.openai_llm.AsyncOpenAI"),
        ):
            yield

    @pytest.mark.asyncio
    async def test_chat_trims_history_to_max(self) -> None:
        llm = OpenAILLM(api_key="test-key", max_history_messages=6)
        llm.client = MagicMock()
        llm.client.chat.completions.create = AsyncMock(
            side_effect=[_make_mock_openai_response(f"reply {i}") for i in range(20)]
        )
        for i in range(20):
            await llm.chat(f"message {i}")
        assert len(llm.history) == 6

    @pytest.mark.asyncio
    async def test_chat_does_not_trim_when_zero(self) -> None:
        llm = OpenAILLM(api_key="test-key", max_history_messages=0)
        llm.client = MagicMock()
        llm.client.chat.completions.create = AsyncMock(
            side_effect=[_make_mock_openai_response(f"reply {i}") for i in range(5)]
        )
        for i in range(5):
            await llm.chat(f"message {i}")
        assert len(llm.history) == 10  # 5 user + 5 assistant

    def test_handle_interrupt_trims(self) -> None:
        llm = OpenAILLM(api_key="test-key", max_history_messages=4)
        llm.history = [{"role": "user", "content": f"u{i}"} for i in range(10)]
        llm.handle_interrupt("partial")
        assert len(llm.history) == 4

    def test_from_config_reads_max_history_messages(self) -> None:
        from animetta.config.providers.llm import OpenAILLMConfig

        config = OpenAILLMConfig(model="gpt-4o-mini", api_key="key", max_history_messages=12)
        llm = OpenAILLM.from_config(config)
        assert llm.max_history_messages == 12

    @pytest.mark.asyncio
    async def test_chat_stream_trims_history_to_max(self) -> None:
        llm = OpenAILLM(api_key="test-key", max_history_messages=4)

        async def response_stream():
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = "reply"
            chunk.usage = None
            yield chunk

        llm.client = MagicMock()
        llm.client.chat.completions.create = AsyncMock(
            side_effect=lambda **_kwargs: response_stream()
        )
        for i in range(5):
            await _drain_stream(llm.chat_stream(f"message {i}"))

        assert len(llm.history) == 4

    @pytest.mark.asyncio
    async def test_chat_with_tools_does_not_mutate_shared_history(self) -> None:
        llm = OpenAILLM(api_key="test-key", max_history_messages=4)
        choice = MagicMock()
        choice.message.content = "reply"
        choice.message.tool_calls = None
        response = MagicMock()
        response.choices = [choice]
        llm.client = MagicMock()
        llm.client.chat.completions.create = AsyncMock(return_value=response)

        for i in range(5):
            await llm.chat_with_tools(f"message {i}", [], [])

        assert llm.history == []


class TestLocalLoraHistoryTrimming:
    def test_from_config_reads_max_history_messages(self) -> None:
        from animetta.config.providers.llm import LocalLoraLLMConfig

        config = LocalLoraLLMConfig(
            base_model_name="test-model",
            lora_path="test-lora",
            device="cpu",
            max_history_messages=7,
        )
        with patch.object(LocalLoraLLM, "load_model"):
            llm = LocalLoraLLM.from_config(config)

        assert llm.max_history_messages == 7

    def test_interrupt_uses_configured_history_limit(self) -> None:
        with patch.object(LocalLoraLLM, "load_model"):
            llm = LocalLoraLLM(device="cpu", max_history_messages=2)
        llm.history = [{"role": "user", "content": str(i)} for i in range(5)]

        llm.handle_interrupt("partial")

        assert len(llm.history) == 2


# ── OllamaLLM: mocked ollama client ───────────────────────────────────────


def _make_mock_ollama_response(content: str = "ok") -> dict:
    return {"message": {"content": content}}


class TestOllamaLLMHistoryTrimming:
    @pytest.mark.skipif(OllamaLLM is None, reason="ollama package not installed")
    @pytest.mark.asyncio
    async def test_chat_trims_history_to_max(self) -> None:
        llm = OllamaLLM(model="llama3", max_history_messages=6)
        llm.client = MagicMock()
        llm.client.chat = MagicMock(
            side_effect=[_make_mock_ollama_response(f"reply {i}") for i in range(20)]
        )
        for i in range(20):
            await llm.chat(f"message {i}")
        assert len(llm.history) == 6

    @pytest.mark.skipif(OllamaLLM is None, reason="ollama package not installed")
    def test_chat_stream_trims_history(self) -> None:
        llm = OllamaLLM(model="llama3", max_history_messages=4)

        def fake_stream(*args, **kwargs):
            yield {"message": {"content": "chunk1"}}
            yield {"message": {"content": "chunk2"}}

        llm.client = MagicMock()
        llm.client.chat = MagicMock(side_effect=fake_stream)
        import asyncio

        for i in range(10):
            asyncio.run(_drain_stream(llm.chat_stream(f"msg {i}")))
        assert len(llm.history) == 4

    @pytest.mark.skipif(OllamaLLM is None, reason="ollama package not installed")
    def test_from_config_reads_max_history_messages(self) -> None:
        from animetta.config.providers.llm import OllamaLLMConfig

        config = OllamaLLMConfig(model="llama3", max_history_messages=14)
        llm = OllamaLLM.from_config(config)
        assert llm.max_history_messages == 14


async def _drain_stream(generator) -> None:
    async for _ in generator:
        pass
