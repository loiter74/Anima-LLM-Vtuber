from __future__ import annotations

from animetta.services.llm import LLMInterface

"""Tests for LangChain ChatModel adapter.

Covers ``create_chat_model_from_service`` and ``LLMChatModelAdapter``
which wrap existing LLMInterface implementations as LangChain's
``BaseChatModel`` for tool binding and streaming compatibility.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatResult

from animetta.services.llm.langchain_adapter import (
    LLMChatModelAdapter,
    create_chat_model_from_service,
)

# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _make_llm_service_mock():
    """Build a mock that fulfills the ``LLMInterface`` protocol.

    Returns a MagicMock with ``spec=LLMInterface`` so Pydantic's
    isinstance check passes, plus a ``chat_stream`` that yields
    canned tokens the adapter can collect into an ``AIMessage``.
    """

    mock = MagicMock(spec=LLMInterface)
    mock.set_system_prompt = MagicMock()
    mock.close = AsyncMock()

    async def _stream(_):
        for chunk in ["Hello", " ", "world", "!"]:
            yield chunk

    mock.chat_stream = _stream

    # Give it a config-like object for model name detection
    mock.config = MagicMock()
    mock.config.model = "test-model"
    mock.config.type = "test-type"
    return mock


def _make_messages(
    human: str = "Hello",
    system: str | None = None,
) -> list:
    """Build a list of LangChain messages.

    Typical call: ``_make_messages(human="Hi", system="Be polite")``.
    """
    msgs = []
    if system:
        msgs.append(SystemMessage(content=system))
    msgs.append(HumanMessage(content=human))
    return msgs


# ═══════════════════════════════════════════════════════════════════════
# create_chat_model_from_service
# ═══════════════════════════════════════════════════════════════════════


class TestCreateChatModelFromService:
    """``create_chat_model_from_service()`` — factory entry point."""

    def test_returns_adapter_instance(self):

        mock_svc = _make_llm_service_mock()
        adapter = create_chat_model_from_service(mock_svc)

        assert isinstance(adapter, LLMChatModelAdapter)

    def test_detects_model_name_from_config(self):

        mock_svc = _make_llm_service_mock()
        adapter = create_chat_model_from_service(mock_svc)

        assert adapter.model_name == "test-model"

    def test_unwraps_tracing_proxy(self):
        """When ``llm_service`` has ``_target``, the adapter uses the inner service's config."""

        inner_svc = _make_llm_service_mock()
        # Simulate TracingProxy wrapper (plain MagicMock is OK here — it is checked
        # for _target BEFORE Pydantic validation)
        outer = MagicMock(spec=LLMInterface)
        outer._target = inner_svc
        # Note: after unwrapping, the code reads model_name from the INNER service's config,
        # which has model="test-model" from _make_llm_service_mock()
        outer.config = MagicMock()
        outer.config.model = "inner-model"

        adapter = create_chat_model_from_service(outer)

        # After unwrapping, model_name comes from the inner service config
        assert adapter.model_name == "test-model"

    def test_falls_back_on_config_model_attr(self):
        """When ``config.model`` is absent, falls back to ``config.type``."""

        mock_svc = MagicMock(spec=LLMInterface)
        mock_svc.close = AsyncMock()
        mock_svc.set_system_prompt = MagicMock()
        mock_svc.config = MagicMock(spec=[])
        # 'model' not set on config so hasattr returns False
        mock_svc.config.type = "fallback-type"

        adapter = create_chat_model_from_service(mock_svc)
        assert adapter.model_name == "fallback-type"

    def test_default_model_name_when_no_config(self):
        """When service has no ``config``, model_name is ``unknown``."""

        # Mock without config attribute — spec limits available attrs
        mock_svc = MagicMock(spec=LLMInterface)
        mock_svc.close = AsyncMock()
        mock_svc.set_system_prompt = MagicMock()
        # Ensure no config attribute
        if hasattr(mock_svc, "config"):
            del mock_svc.config

        adapter = create_chat_model_from_service(mock_svc)
        # Should still create the adapter with default model_name
        assert adapter.model_name == "unknown"


# ═══════════════════════════════════════════════════════════════════════
# LLMChatModelAdapter — properties
# ═══════════════════════════════════════════════════════════════════════


class TestLLMChatModelAdapterProperties:
    """Static attributes and properties of the adapter."""

    def test_llm_type(self):

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc, model_name="gpt-4")

        assert adapter._llm_type == "anima_gpt-4"

    def test_lc_secrets_empty(self):

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc)
        assert adapter.lc_secrets == {}


# ═══════════════════════════════════════════════════════════════════════
# LLMChatModelAdapter — _agenerate (async)
# ═══════════════════════════════════════════════════════════════════════


class TestLLMChatModelAdapterAGenerate:
    """LLMChatModelAdapter._agenerate() — async generation."""

    @pytest.mark.asyncio
    async def test_generates_response_from_human_message(self):

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc)

        messages = _make_messages(human="Hi")
        result = await adapter._agenerate(messages)

        assert isinstance(result, ChatResult)
        assert len(result.generations) == 1
        assert result.generations[0].text == "Hello world!"

    @pytest.mark.asyncio
    async def test_sets_system_prompt(self):

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc)

        messages = _make_messages(human="Hi", system="You are a bot.")
        await adapter._agenerate(messages)

        mock_svc.set_system_prompt.assert_called_once_with("You are a bot.")

    @pytest.mark.asyncio
    async def test_empty_human_input_returns_fallback(self):

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc)

        # No HumanMessage — only system
        messages = [SystemMessage(content="Be helpful.")]
        result = await adapter._agenerate(messages)

        assert "Sorry" in result.generations[0].text

    @pytest.mark.asyncio
    async def test_stream_notifies_run_manager(self):
        from langchain_core.callbacks.manager import CallbackManagerForLLMRun

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc)

        run_manager = MagicMock(spec=CallbackManagerForLLMRun)
        run_manager.on_llm_new_token = AsyncMock()

        messages = _make_messages(human="Hello")
        await adapter._agenerate(messages, run_manager=run_manager)

        # Each chunk should have triggered a callback
        assert run_manager.on_llm_new_token.await_count >= 1

    @pytest.mark.asyncio
    async def test_handles_generation_error(self):

        mock_svc = MagicMock(spec=LLMInterface)

        async def _broken_stream(_):
            raise RuntimeError("API error")

        mock_svc.chat_stream = _broken_stream
        mock_svc.set_system_prompt = MagicMock()
        mock_svc.close = AsyncMock()

        adapter = LLMChatModelAdapter(llm_service=mock_svc)
        messages = _make_messages(human="Hi")

        result = await adapter._agenerate(messages)

        # Error is caught and embedded in the response
        assert "Error" in result.generations[0].text

    @pytest.mark.asyncio
    async def test_uses_latest_human_message(self):
        """Only the last HumanMessage is used as user input."""

        collected = []

        async def _capture_stream(text):
            collected.append(text)
            yield "ok"

        mock_svc = MagicMock(spec=LLMInterface)
        mock_svc.chat_stream = _capture_stream
        mock_svc.set_system_prompt = MagicMock()
        mock_svc.close = AsyncMock()

        adapter = LLMChatModelAdapter(llm_service=mock_svc)
        messages = [
            SystemMessage(content="Bot."),
            HumanMessage(content="First message"),
            AIMessage(content="First reply"),
            HumanMessage(content="Second message"),
        ]
        await adapter._agenerate(messages)

        # Only the last human message should be passed
        assert collected == ["Second message"]


# ═══════════════════════════════════════════════════════════════════════
# LLMChatModelAdapter — _generate (sync bridge)
# ═══════════════════════════════════════════════════════════════════════


class TestLLMChatModelAdapterGenerate:
    """LLMChatModelAdapter._generate() — sync bridge to async."""

    def test_sync_generate_bridges_to_async(self):

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc)

        messages = _make_messages(human="Hi")
        result = adapter._generate(messages)

        assert isinstance(result, ChatResult)
        assert len(result.generations) == 1


# ═══════════════════════════════════════════════════════════════════════
# LLMChatModelAdapter — bind_tools
# ═══════════════════════════════════════════════════════════════════════


class TestLLMChatModelAdapterBindTools:
    """LLMChatModelAdapter.bind_tools() — tool registration."""

    def test_stores_tools_in_bound_tools(self):

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc)

        tool1 = MagicMock()
        tool1.name = "search"
        tool2 = MagicMock()
        tool2.name = "calculator"

        result = adapter.bind_tools([tool1, tool2])

        assert result is adapter  # returns self
        assert len(adapter.bound_tools) == 2
        assert adapter.bound_tools[0].name == "search"

    def test_accepts_empty_list(self):

        mock_svc = _make_llm_service_mock()
        adapter = LLMChatModelAdapter(llm_service=mock_svc)

        adapter.bind_tools([])
        assert adapter.bound_tools == []


# ═══════════════════════════════════════════════════════════════════════
# LLMChatModelAdapter — full flow: create, bind, generate
# ═══════════════════════════════════════════════════════════════════════


class TestLLMChatModelAdapterFullFlow:
    """Integration-style tests exercising the full create→bind→generate path."""

    @pytest.mark.asyncio
    async def test_create_bind_generate(self):

        mock_svc = _make_llm_service_mock()
        chat_model = create_chat_model_from_service(mock_svc, _enable_tooling=True)

        tool = MagicMock()
        tool.name = "web_search"
        chat_model.bind_tools([tool])

        messages = _make_messages(human="Search for AI news")
        result = await chat_model._agenerate(messages)

        assert isinstance(result, ChatResult)
        assert len(result.generations) == 1
        assert "AI" in result.generations[0].text or "Hello" in result.generations[0].text
