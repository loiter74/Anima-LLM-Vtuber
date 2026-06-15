from __future__ import annotations

from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator

"""Tests for LangGraph orchestrator — initialization and input processing."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_graph():
    """Return a compiled mock graph with ainvoke."""
    graph = AsyncMock()
    graph.ainvoke = AsyncMock(return_value={
        "response_text": "mock reply",
        "response_chunks": ["mock reply"],
        "emotion": "neutral",
    })
    return graph


@pytest.fixture
def orchestrator(mock_service_context, mock_socketio, mock_graph, monkeypatch):
    """Create an orchestrator with mocked dependencies."""
    monkeypatch.setattr(
        "animetta.orchestration.graph.orchestrator.create_default_graph",
        lambda *a, **kw: mock_graph,
    )
    monkeypatch.setattr(
        "animetta.orchestration.graph.orchestrator.ToolManager",
        lambda *a, **kw: MagicMock(load_tools=AsyncMock()),
    )
    monkeypatch.setattr(
        "animetta.orchestration.graph.orchestrator.get_observability",
        lambda: MagicMock(),
    )

    orch = LangGraphOrchestrator(
        service_context=mock_service_context,
        socketio=mock_socketio,
        enable_tools=False,
    )
    return orch


class TestOrchestratorInit:
    """Orchestrator creation and start/stop."""

    @pytest.mark.asyncio
    async def test_init_sets_session_id(self, orchestrator):
        """Session ID should be taken from service_context."""
        assert orchestrator.session_id is not None
        assert orchestrator._langgraph_config is not None

    @pytest.mark.asyncio
    async def test_start_sets_running(self, orchestrator):
        """After start, _is_running should be True."""
        await orchestrator.start()
        assert orchestrator._is_running is True

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, orchestrator):
        """After stop, _is_running should be False."""
        await orchestrator.start()
        await orchestrator.stop()
        assert orchestrator._is_running is False


class TestOrchestratorProcessText:
    """Text processing flow."""

    @pytest.mark.asyncio
    async def test_process_text_before_start_returns_error(self, orchestrator):
        """Calling process_text before start returns error."""
        result = await orchestrator.process_text(text="hello")
        assert "error" in result
        assert "not started" in result["error"].lower() or "未启动" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_process_text_returns_response(self, orchestrator):
        """process_text returns the graph output through _clean_result."""
        await orchestrator.start()
        result = await orchestrator.process_text(
            text="hello",
            user_id="user1",
            user_name="Alice",
        )
        assert "response_text" in result
        assert result["response_text"] == "mock reply"


class TestOrchestratorProcessAudio:
    """Audio processing flow."""

    @pytest.mark.asyncio
    async def test_process_audio_before_start_returns_error(self, orchestrator):
        """Calling process_audio before start returns error."""
        result = await orchestrator.process_audio(audio_data=b"fake_audio")
        assert "error" in result
        assert "not started" in result["error"].lower() or "未启动" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_process_audio_returns_response(self, orchestrator):
        """process_audio returns the graph output."""
        await orchestrator.start()
        result = await orchestrator.process_audio(
            audio_data=b"fake_audio",
            user_id="user1",
        )
        assert "response_text" in result
