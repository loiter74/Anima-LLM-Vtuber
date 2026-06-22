from __future__ import annotations

"""Tests for ASR (speech recognition) node."""

import pytest
from langgraph.types import RunnableConfig

from animetta.orchestration.graph import asr_node
from animetta.orchestration.graph.state import create_initial_state


class TestAsrNode:
    """ASR node: transcribe raw audio to user_text."""

    @pytest.mark.asyncio
    async def test_successful_transcription(self, mock_service_context):
        """Raw audio is transcribed to text and a HumanMessage is created."""

        state = create_initial_state(
            session_id="test",
            raw_audio=b"fake_audio_bytes",
        )
        config = RunnableConfig(
            configurable={"service_context": mock_service_context}
        )

        result = await asr_node(state, config)

        assert result["user_text"] == "mock transcription text"
        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "mock transcription text"
        assert result["messages"][0].name == "user"
        mock_service_context.asr_engine.transcribe.assert_awaited_once_with(
            b"fake_audio_bytes"
        )

    @pytest.mark.asyncio
    async def test_missing_audio_returns_error(self):
        """When raw_audio is absent, return error and empty text."""

        state = create_initial_state(session_id="test", raw_audio=None)
        result = await asr_node(state)

        assert result["error"] == "No audio data"
        assert result["user_text"] == ""

    @pytest.mark.asyncio
    async def test_missing_audio_skips_asr(self):
        """State without raw_audio key should also be handled."""

        state = create_initial_state(session_id="test")
        # deliberately remove raw_audio
        state.pop("raw_audio", None)
        result = await asr_node(state)

        assert result["error"] == "No audio data"
        assert result["user_text"] == ""

    @pytest.mark.asyncio
    async def test_no_service_context_returns_error(self):
        """Without service_context in config, return error."""

        state = create_initial_state(
            session_id="test",
            raw_audio=b"fake_audio_bytes",
        )
        config = RunnableConfig(configurable={})
        result = await asr_node(state, config)

        assert result["error"] == "service_context not configured"
        assert result["user_text"] == ""

    @pytest.mark.asyncio
    async def test_no_asr_engine_returns_error(self, mock_service_context):
        """When service_context lacks an ASR engine, return error."""

        mock_service_context.asr_engine = None

        state = create_initial_state(
            session_id="test",
            raw_audio=b"fake_audio_bytes",
        )
        config = RunnableConfig(
            configurable={"service_context": mock_service_context}
        )
        result = await asr_node(state, config)

        assert result["error"] == "ASR engine not initialized"
        assert result["user_text"] == ""

    @pytest.mark.asyncio
    async def test_transcription_failure_returns_error(self, mock_service_context):
        """When ASR engine raises, return error with the exception message."""

        mock_service_context.asr_engine.transcribe = pytest.fail
        # use AsyncMock that raises
        import unittest.mock
        mock_service_context.asr_engine.transcribe = unittest.mock.AsyncMock(
            side_effect=RuntimeError("connection refused")
        )

        state = create_initial_state(
            session_id="test",
            raw_audio=b"fake_audio",
        )
        config = RunnableConfig(
            configurable={"service_context": mock_service_context}
        )
        result = await asr_node(state, config)

        assert "connection refused" in result.get("error", "")
        assert result["user_text"] == ""

    @pytest.mark.asyncio
    async def test_with_user_name_prefixes_message(self, mock_service_context):
        """When user_name is in state, message content should include it."""

        state = create_initial_state(
            session_id="test",
            raw_audio=b"audio",
            user_name="Alice",
            user_id="user_1",
        )
        config = RunnableConfig(
            configurable={"service_context": mock_service_context}
        )
        result = await asr_node(state, config)

        assert result["user_text"] == "mock transcription text"
        assert "[Alice]: mock transcription text" in result["messages"][0].content
        assert result["messages"][0].name == "user_1"

    @pytest.mark.asyncio
    async def test_socketio_emission_on_transcription(self, mock_service_context):
        """Transcript is emitted via socketio when present in config."""
        from unittest.mock import AsyncMock

        mock_sio = AsyncMock()

        state = create_initial_state(
            session_id="test_session",
            raw_audio=b"audio",
        )
        config = RunnableConfig(
            configurable={
                "service_context": mock_service_context,
                "socketio": mock_sio,
            }
        )
        result = await asr_node(state, config)

        assert result["user_text"] == "mock transcription text"
        mock_sio.emit.assert_awaited_once_with(
            "chat:transcript",
            {"text": "mock transcription text", "is_final": True},
            to="test_session",
        )

    @pytest.mark.asyncio
    async def test_socketio_emission_silent_on_failure(self, mock_service_context):
        """SocketIO emission failure should not crash the node."""
        from unittest.mock import AsyncMock

        mock_sio = AsyncMock()
        mock_sio.emit = AsyncMock(side_effect=RuntimeError("emit failed"))

        state = create_initial_state(
            session_id="test",
            raw_audio=b"audio",
        )
        config = RunnableConfig(
            configurable={
                "service_context": mock_service_context,
                "socketio": mock_sio,
            }
        )
        result = await asr_node(state, config)

        # Node should still succeed even though socketio emit failed
        assert result["user_text"] == "mock transcription text"
