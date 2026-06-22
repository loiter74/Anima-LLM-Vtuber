from __future__ import annotations

"""Tests for LLM reasoning node — tool-calling and streaming paths."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.types import RunnableConfig

from animetta.orchestration.graph import llm_node
from animetta.orchestration.graph.llm_node import FALLBACK_RESPONSE
from animetta.orchestration.graph.state import create_initial_state


def _make_config(service_context=None, enable_tools=False, chat_model=None):
    """Helper to build a RunnableConfig with test overrides."""
    configurable = {}
    if service_context:
        configurable["service_context"] = service_context
    if enable_tools:
        configurable["enable_tools"] = True
    if chat_model:
        configurable["chat_model"] = chat_model
    # Prevent MemoryMiddleware auto-creation from mock memory_system
    configurable["memory_middleware"] = None
    return RunnableConfig(configurable=configurable)


# ── Empty / error inputs ──────────────────────────────────────────


class TestLLMNodeErrors:
    """Edge cases and invalid inputs."""

    @pytest.mark.asyncio
    async def test_empty_user_text_returns_error(self):
        """Empty user_text should immediately return an error without calling LLM."""

        state = create_initial_state(
            session_id="test-session",
            user_text="",
        )
        result = await llm_node(state)
        assert result.get("error") is not None
        assert "No user text" in result.get("error", "") or "无用户文本" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_no_service_context_returns_error(self):
        """Missing service_context in config returns error."""

        state = create_initial_state(
            session_id="test-session",
            user_text="你好",
        )
        # Config without service_context
        config = RunnableConfig(configurable={})
        result = await llm_node(state, config)
        assert result.get("error") is not None
        assert "service_context" in result["error"]

    @pytest.mark.asyncio
    async def test_no_llm_engine_returns_error(self, mock_service_context):
        """Service context without llm_engine returns error."""

        ctx = MagicMock()
        ctx.llm_engine = None
        ctx.core.config = None

        state = create_initial_state(
            session_id="test-session",
            user_text="你好",
        )
        config = _make_config(service_context=ctx)
        result = await llm_node(state, config)
        assert result.get("error") is not None
        assert "not initialized" in result["error"].lower() or "LLM" in result.get("error", "")


# ── Streaming path (no tools) ─────────────────────────────────────


class TestLLMNodeWithoutTools:
    """Normal streaming response, no tool calling."""

    @pytest.mark.asyncio
    async def test_streaming_returns_response_text(self, mock_service_context):
        """llm_node returns response_text from streaming LLM."""

        async def _chat_stream(user_text, system_prompt=""):
            yield "Hello"
            yield " world"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="Hi there",
            system_prompt="You are a helpful assistant.",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result.get("response_text") == "Hello world"
        assert result["response_chunks"] == ["Hello", " world"]
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_streaming_empty_response(self, mock_service_context):
        """Empty stream should result in empty response_text."""

        async def _chat_stream(user_text, system_prompt=""):
            if False:
                yield
            return

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="hello",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result.get("response_text") == ""
        assert result["response_chunks"] == []
        assert result["messages"] is not None

    @pytest.mark.asyncio
    async def test_streaming_injects_system_prompt(self, mock_service_context):
        """System prompt from state should be passed to LLM."""

        captured_system_prompt = None

        async def _chat_stream(user_text, system_prompt=""):
            nonlocal captured_system_prompt
            captured_system_prompt = system_prompt
            yield "response"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="hello",
            system_prompt="Be funny",
        )
        config = _make_config(service_context=mock_service_context)
        await llm_node(state, config)

        # Verify system_prompt was passed to the LLM
        assert captured_system_prompt is not None
        assert "Be funny" in captured_system_prompt


# ── Tool-calling path ─────────────────────────────────────────────


class TestLLMNodeWithTools:
    """Tool-augmented LLM responses."""

    @pytest.mark.asyncio
    async def test_tool_call_returns_tool_calls(self, mock_service_context):
        """When LLM returns tool_calls, they should be in the result."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [
            MagicMock(name="web_search", description="Search the web"),
            MagicMock(name="calculator", description="Do math"),
        ]

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "Let me search for that",
                "tool_calls": [
                    {"id": "call_1", "name": "web_search", "args": {"query": "weather"}},
                ],
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["tool_calls"] is not None
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "web_search"
        assert result["tool_calls"][0]["args"]["query"] == "weather"

    @pytest.mark.asyncio
    async def test_tool_call_without_tools_returns_text(self, mock_service_context):
        """When LLM returns content without tool_calls, response_text is set."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "The weather is sunny today!",
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["tool_calls"] is None
        assert result["response_text"] == "The weather is sunny today!"

    @pytest.mark.asyncio
    async def test_tool_call_error_falls_back_to_streaming(self, mock_service_context):
        """When chat_with_tools raises, it should fall back to streaming path."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [MagicMock(name="web_search")]

        # Tool path raises
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            side_effect=Exception("API error")
        )

        # Streaming path works
        async def _chat_stream(user_text, system_prompt=""):
            yield "Fallback response"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        # Should not raise — falls back to streaming
        result = await llm_node(state, config)

        assert result["tool_calls"] is None
        assert result["response_text"] == "Fallback response"


# ── Timeout / Error Resilience ────────────────────────────────────


class TestLLMTimeout:
    """LLM timeout triggers fallback response with error metadata."""

    @pytest.mark.asyncio
    async def test_llm_timeout_triggers_fallback(self, mock_service_context):
        """When LLM streaming times out, fallback text is returned, no exception propagates."""

        async def _chat_stream_hangs(user_text, system_prompt=""):
            await asyncio.sleep(999)
            yield "never"

        mock_service_context.llm_engine.chat_stream = _chat_stream_hangs

        state = create_initial_state(
            session_id="test-timeout",
            user_text="Hello",
        )
        config = _make_config(service_context=mock_service_context)
        config["configurable"]["llm_timeout"] = 0.001

        result = await llm_node(state, config)

        assert result["response_text"] == FALLBACK_RESPONSE
        assert result["response_chunks"] == [FALLBACK_RESPONSE]
        assert result["tool_calls"] is None
        assert result.get("metadata", {}).get("error_type") == "timeout"

    @pytest.mark.asyncio
    async def test_fallback_is_per_turn(self, mock_service_context):
        """After timeout on turn N, turn N+1 attempts real provider again."""

        # Turn 1: force timeout → fallback
        async def _chat_stream_timeout(user_text, system_prompt=""):
            await asyncio.sleep(999)
            yield "never"

        mock_service_context.llm_engine.chat_stream = _chat_stream_timeout

        state1 = create_initial_state(
            session_id="test-per-turn",
            user_text="hi",
        )
        config1 = _make_config(service_context=mock_service_context)
        config1["configurable"]["llm_timeout"] = 0.001

        result1 = await llm_node(state1, config1)
        assert result1.get("metadata", {}).get("error_type") == "timeout"

        # Turn 2: real provider works normally
        async def _chat_stream_real(user_text, system_prompt=""):
            yield "real response"

        mock_service_context.llm_engine.chat_stream = _chat_stream_real

        state2 = create_initial_state(
            session_id="test-per-turn",
            user_text="hello again",
        )
        config2 = _make_config(service_context=mock_service_context)
        config2["configurable"]["llm_timeout"] = 30

        result2 = await llm_node(state2, config2)
        assert result2["response_text"] == "real response"
        assert "error_type" not in result2.get("metadata", {})
