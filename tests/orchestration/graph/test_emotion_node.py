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
    async def test_missing_marker_does_not_invoke_legacy_analyzer(self, mock_service_context):
        """Missing markers deterministically fall back instead of guessing."""

        mock_service_context.emotion_analyzer.extract = MagicMock()

        state = create_initial_state(session_id="test")
        state["response_text"] = "I am so happy!"
        config = RunnableConfig(configurable={"service_context": mock_service_context})
        result = await emotion_node(state, config)
        assert result["emotion"] == "neutral"
        assert result["performance_plan"]["base"] == "calm"
        mock_service_context.emotion_analyzer.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_analyzer_is_not_part_of_semantic_control(self, mock_service_context):
        """Semantic control is independent of the legacy analyzer."""

        mock_service_context.emotion_analyzer.extract = MagicMock(side_effect=ValueError("fail"))

        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello"
        config = RunnableConfig(configurable={"service_context": mock_service_context})
        result = await emotion_node(state, config)
        assert result["emotion"] == "neutral"
        mock_service_context.emotion_analyzer.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_semantic_marker_builds_performance_plan_and_compatible_vad(self):
        state = create_initial_state(session_id="test")
        state["response_text"] = "本小姐早就知道了。"
        state["response_chunks"] = ["[live2d:smug|subtle|skeptical] 本小姐早就知道了。"]

        result = await emotion_node(state)

        assert result["performance_plan"] == {
            "version": 1,
            "base": "calm",
            "intensity": "subtle",
            "accent": "none",
            "source": "legacy",
        }
        assert result["emotion"] == "neutral"
        assert result["response_emotion"] == "neutral"
        assert result["response_emotion_vad"] == result["emotion_vad"]
        assert result["metadata"]["live2d_performance"] == {
            "source": "legacy",
            "base": "calm",
            "accent": "none",
            "fallback": "none",
        }

    @pytest.mark.asyncio
    async def test_missing_marker_uses_calm_fallback_without_analyzer(self):
        state = create_initial_state(session_id="test")
        state["response_text"] = "普通回复。"

        result = await emotion_node(state)

        assert result["performance_plan"] == {
            "version": 1,
            "base": "calm",
            "intensity": "subtle",
            "accent": "none",
            "source": "fallback",
        }
        assert result["emotion"] == "neutral"
        assert result["metadata"]["live2d_performance"]["fallback"] == "missing_marker"

    @pytest.mark.asyncio
    async def test_legacy_marker_maps_to_semantic_plan(self):
        state = create_initial_state(session_id="test")
        state["response_text"] = "你好，很高兴见到你。"
        state["response_chunks"] = ["你好，[happy] 很高兴见到你。"]

        result = await emotion_node(state)

        assert result["performance_plan"]["base"] == "calm"
        assert result["performance_plan"]["source"] == "legacy"
        assert result["emotion"] == "happy"

    @pytest.mark.asyncio
    async def test_marker_can_span_streaming_response_chunks(self):
        state = create_initial_state(session_id="test")
        state["response_text"] = "让我想想。"
        state["response_chunks"] = [
            "[live2d:thinking|",
            "subtle|skeptical] ",
            "让我想想。",
        ]

        result = await emotion_node(state)

        assert result["performance_plan"]["base"] == "calm"
        assert result["performance_plan"]["accent"] == "none"
        assert result["emotion"] == "thinking"
