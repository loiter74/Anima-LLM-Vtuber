from __future__ import annotations

"""Tests for output distribution node — Socket.IO + memory storage."""

from unittest.mock import AsyncMock

import pytest
from langgraph.types import RunnableConfig

from animetta.orchestration.graph import output_node
from animetta.orchestration.graph.state import create_initial_state


class TestOutputNode:
    """Output node: emit events via Socket.IO and store to memory."""

    @pytest.mark.asyncio
    async def test_no_socketio_returns_error(self):
        """Without Socket.IO in config, returns error."""

        state = create_initial_state(session_id="test")
        config = RunnableConfig(configurable={})
        result = await output_node(state, config)
        assert result.get("error") is not None

    @pytest.mark.asyncio
    async def test_emits_conversation_start_and_end(self, mock_socketio, mock_service_context):
        """Always emits conversation-start and conversation-end control signals."""

        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello"
        config = RunnableConfig(configurable={
            "socketio": mock_socketio,
            "service_context": mock_service_context,
        })
        await output_node(state, config)

        # Check control signals
        control_calls = [
            c for c in mock_socketio.emit.call_args_list
            if c[0][0] == "chat:control"
        ]
        signals = [c[0][1]["signal"] for c in control_calls]
        assert "conversation-start" in signals
        assert "conversation-end" in signals

    @pytest.mark.asyncio
    async def test_emits_text_when_response_exists(self, mock_socketio, mock_service_context):
        """response_text triggers sentence events."""

        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello world"
        config = RunnableConfig(configurable={
            "socketio": mock_socketio,
            "service_context": mock_service_context,
        })
        await output_node(state, config)

        sentence_calls = [
            c for c in mock_socketio.emit.call_args_list
            if c[0][0] == "chat:sentence"
        ]
        assert len(sentence_calls) >= 1
        # First sentence call should have the text
        assert sentence_calls[0][0][1]["text"] == "Hello world"

    @pytest.mark.asyncio
    async def test_emits_expression_for_emotion(self, mock_socketio, mock_service_context):
        """Emotion in state triggers expression event + Live2D motion."""

        state = create_initial_state(session_id="test")
        state["response_text"] = "I'm happy"
        state["emotion"] = "happy"
        config = RunnableConfig(configurable={
            "socketio": mock_socketio,
            "service_context": mock_service_context,
        })
        await output_node(state, config)

        expr_calls = [
            c for c in mock_socketio.emit.call_args_list
            if c[0][0] == "chat:expression"
        ]
        assert len(expr_calls) >= 1
        assert expr_calls[0][0][1]["emotion"] == "happy"

        action_calls = [
            c for c in mock_socketio.emit.call_args_list
            if c[0][0] == "chat:live2d_action"
        ]
        assert len(action_calls) >= 1
        assert action_calls[0][0][1]["index"] == 3  # happy -> 3

    @pytest.mark.asyncio
    async def test_memory_storage_called(self, mock_socketio, mock_service_context):
        """Memory system encode should be called with conversation data."""

        mock_service_context.memory_system.encode = AsyncMock()

        state = create_initial_state(
            session_id="test",
            user_text="Hi there",
            user_name="Alice",
        )
        state["response_text"] = "Hello Alice!"
        state["emotion"] = "neutral"
        config = RunnableConfig(configurable={
            "socketio": mock_socketio,
            "service_context": mock_service_context,
        })
        await output_node(state, config)

        # Verify memory storage was called
        mock_service_context.memory_system.encode.assert_called_once()
        call_kwargs = mock_service_context.memory_system.encode.call_args
        assert call_kwargs.kwargs["user_input"] == "Hi there"
        assert call_kwargs.kwargs["agent_response"] == "Hello Alice!"
