from __future__ import annotations

from animetta.orchestration.graph import stats_store
from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator
from animetta.orchestration.graph.stats_store import StatsStore, close_stats_store

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

    @pytest.mark.asyncio
    async def test_process_text_persists_dialogue_and_node_snapshots(
        self, orchestrator, mock_graph, tmp_path
    ):
        """process_text stores conversation text and per-node debug spans."""
        await close_stats_store()
        store = StatsStore(db_path=str(tmp_path / "stats.db"))
        await store.init()
        stats_store._store = store
        mock_graph.ainvoke.return_value = {
            "user_text": "为什么一直未采集？",
            "response_text": "因为之前没有把节点快照写进 stats.db。",
            "response_chunks": ["因为之前没有把节点快照写进 stats.db。"],
            "tts_audio": b"RIFF....",
            "emotion": "thinking",
            "_timings": [
                {"step": "llm.api_call", "duration_ms": 1234.5, "detail": "chat_stream"},
                {"step": "tts.synthesize", "duration_ms": 456.7, "detail": "edge_tts"},
            ],
        }

        try:
            await orchestrator.start()
            result = await orchestrator.process_text(text="为什么一直未采集？")
            trace_id = orchestrator._stats_handler._trace_id

            turn = await store.get_conversation_turn(trace_id)
            detail = await store.get_trace_detail(trace_id)

            assert result["response_text"] == "因为之前没有把节点快照写进 stats.db。"
            assert turn is not None
            assert turn["user_text"] == "为什么一直未采集？"
            assert turn["assistant_text"] == "因为之前没有把节点快照写进 stats.db。"
            assert detail is not None
            spans = {span["node_name"]: span for span in detail["spans"]}
            assert spans["llm"]["input_summary"] == "为什么一直未采集？"
            assert spans["llm"]["output_summary"] == "因为之前没有把节点快照写进 stats.db。"
            assert spans["tts"]["input_summary"] == "因为之前没有把节点快照写进 stats.db。"
            assert spans["emotion"]["output_summary"] == "thinking"
            assert spans["output"]["output_summary"] == "因为之前没有把节点快照写进 stats.db。"
        finally:
            await close_stats_store()


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
