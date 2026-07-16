from __future__ import annotations

"""Tests for emotion analysis node."""

from unittest.mock import MagicMock

import pytest
from langgraph.types import RunnableConfig

from animetta.orchestration.graph import emotion_node
from animetta.orchestration.graph.state import create_initial_state


class TestEmotionNode:
    """Emotion node: extract emotion from response text."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_default_emotion(self):
        """No response_text should default to neutral."""

        state = create_initial_state(session_id="test")
        state["response_text"] = ""
        result = await emotion_node(state)
        assert result["emotion"] == "neutral"
        assert result["response_emotion"] == "neutral"
        assert result["response_emotion_vad"] == result["emotion_vad"]

    @pytest.mark.asyncio
    async def test_no_analyzer_in_config_returns_neutral(self):
        """Without emotion_analyzer or service_context, default to neutral."""

        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello world"
        config = RunnableConfig(configurable={})
        result = await emotion_node(state, config)
        assert result["emotion"] == "neutral"

    @pytest.mark.asyncio
    async def test_analyzer_via_service_context(self, mock_service_context):
        """emotion_analyzer from service_context is used when available."""

        mock_result = MagicMock()
        mock_result.primary = "happy"
        mock_result.confidence = 0.95

        mock_service_context.emotion_analyzer.extract = MagicMock(return_value=mock_result)

        state = create_initial_state(session_id="test")
        state["response_text"] = "I am so happy!"
        config = RunnableConfig(configurable={"service_context": mock_service_context})
        result = await emotion_node(state, config)
        assert result["emotion"] == "happy"

    @pytest.mark.asyncio
    async def test_analyzer_error_returns_default(self, mock_service_context):
        """If the analyzer raises, fall back to neutral."""

        mock_service_context.emotion_analyzer.extract = MagicMock(side_effect=ValueError("fail"))

        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello"
        config = RunnableConfig(configurable={"service_context": mock_service_context})
        result = await emotion_node(state, config)
        assert result["emotion"] == "neutral"
