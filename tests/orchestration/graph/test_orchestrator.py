from __future__ import annotations

from animetta.observability.ports import NoOpObservationRecorder
from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator

"""Tests for LangGraph orchestrator — initialization and input processing."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio


class CaptureRecorder(NoOpObservationRecorder):
    def __init__(self):
        self.started = []
        self.finished = []
        self.flushes = 0

    async def start_trace(self, record):
        self.started.append(record)

    async def finish_trace(self, trace_id, outcome, **kwargs):
        self.finished.append((trace_id, outcome, kwargs))

    async def flush(self):
        self.flushes += 1


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


@pytest_asyncio.fixture
async def orchestrator(mock_service_context, mock_socketio, mock_graph, monkeypatch):
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

    recorder = CaptureRecorder()
    orch = LangGraphOrchestrator(
        service_context=mock_service_context,
        socketio=mock_socketio,
        enable_tools=False,
        observation_recorder=recorder,
    )
    orch.test_recorder = recorder
    yield orch


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
    async def test_process_text_records_canonical_root_without_synthetic_snapshots(
        self, orchestrator, mock_graph
    ):
        mock_graph.ainvoke.return_value = {
            "user_text": "为什么一直未采集？",
            "response_text": "现在记录真实节点。",
            "response_chunks": ["现在记录真实节点。"],
            "tts_audio": b"RIFF....",
            "emotion": "thinking",
        }

        await orchestrator.start()
        result = await orchestrator.process_text(
            text="为什么一直未采集？",
            message_id="message-1",
            conversation_id="conversation-1",
            task_id="task-1",
        )

        assert result["response_text"] == "现在记录真实节点。"
        assert orchestrator.test_recorder.started[0].trace_id == "task-1"
        assert orchestrator.test_recorder.finished[0][0] == "task-1"
        assert orchestrator.test_recorder.flushes == 1
        assert not hasattr(orchestrator, "_stats_handler")

    @pytest.mark.asyncio
    async def test_golden_observation_persists_identity_without_content(
        self, orchestrator, mock_graph
    ):
        orchestrator.service_context.config.system.runtime_profile = "golden"
        mock_graph.ainvoke.return_value = {
            "user_text": "private user text",
            "response_text": "private assistant text",
            "metadata": {"dialogue_status": "composer"},
        }
        await orchestrator.start()
        await orchestrator.process_text(
            text="private user text",
            message_id="11111111-1111-4111-8111-111111111111",
            conversation_id="22222222-2222-4222-8222-222222222222",
            task_id="33333333-3333-4333-8333-333333333333",
            turn_id="33333333-3333-4333-8333-333333333333",
        )
        trace = orchestrator.test_recorder.started[0]
        finish = orchestrator.test_recorder.finished[0]
        assert trace.user_content.text is None
        assert finish[2]["assistant_content"].text is None
        assert trace.trace_id == finish[0]


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
