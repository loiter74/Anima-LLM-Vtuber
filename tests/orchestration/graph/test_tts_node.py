from __future__ import annotations

"""Tests for TTS synthesis node."""

from unittest.mock import AsyncMock

import pytest
from langgraph.types import RunnableConfig

from animetta.orchestration.graph import tts_node
from animetta.orchestration.graph.state import create_initial_state


class TestTTSNode:
    """TTS node: text-to-speech synthesis."""

    def _make_state(session_id="test", response_text=""):
        state = create_initial_state(session_id=session_id)
        state["response_text"] = response_text
        return state

    @pytest.mark.asyncio
    async def test_empty_text_skips_tts(self):
        """Empty response_text should skip TTS and return None."""

        state = self._make_state(response_text="")
        result = await tts_node(state)
        assert result["tts_audio"] is None

    @pytest.mark.asyncio
    async def test_no_service_context_returns_error(self):
        """Missing service_context returns error."""

        state = self._make_state(response_text="Hello world")
        config = RunnableConfig(configurable={})
        result = await tts_node(state, config)
        assert result.get("error") is not None
        assert result["tts_audio"] is None

    @pytest.mark.asyncio
    async def test_no_tts_engine_skips(self, mock_service_context):
        """Service context without tts_engine skips TTS."""

        ctx = mock_service_context
        ctx.tts_engine = None

        state = self._make_state(response_text="Hello world")
        config = RunnableConfig(
            configurable={"service_context": ctx}
        )
        result = await tts_node(state, config)
        assert result["tts_audio"] is None

    @pytest.mark.asyncio
    async def test_synthesize_returns_audio_bytes(self, mock_service_context):
        """TTS engine returns audio bytes, stored in state."""

        mock_service_context.tts_engine.synthesize = AsyncMock(
            return_value=b"fake_audio_bytes"
        )

        state = self._make_state(response_text="Hello world")
        config = RunnableConfig(
            configurable={"service_context": mock_service_context}
        )
        result = await tts_node(state, config)
        assert result["tts_audio"] == b"fake_audio_bytes"
