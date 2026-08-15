from __future__ import annotations

from animetta.observability.ports import NoOpObservationRecorder
from animetta.orchestration.graph.checkpointing import CheckpointRequest
from animetta.orchestration.graph.conversation_session import ConversationSessionRegistry
from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator

"""Tests for LangGraph orchestrator — initialization and input processing."""

from inspect import signature
from types import SimpleNamespace
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
    graph.ainvoke = AsyncMock(
        return_value={
            "response_text": "mock reply",
            "response_chunks": ["mock reply"],
            "emotion": "neutral",
        }
    )
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

    @pytest.mark.asyncio
    async def test_start_reuses_prebuilt_tool_manager_without_loading_config(
        self, mock_service_context, mock_socketio, monkeypatch
    ):
        """A showcase shares runtime-owned tools instead of starting a second bridge."""

        assert "tool_manager" in signature(LangGraphOrchestrator).parameters
        prebuilt = MagicMock()
        prebuilt.tools = [MagicMock(name="mc_operate_bot")]
        prebuilt.tools_map = {"mc_operate_bot": prebuilt.tools[0]}
        prebuilt.is_loaded.return_value = True
        graph = AsyncMock()
        create_graph = MagicMock(return_value=graph)
        monkeypatch.setattr(
            "animetta.orchestration.graph.orchestrator.create_default_graph",
            create_graph,
        )
        monkeypatch.setattr(
            "animetta.orchestration.graph.orchestrator.get_observability",
            lambda: MagicMock(_initialized=True, callbacks=[]),
        )

        instance = LangGraphOrchestrator(
            service_context=mock_service_context,
            socketio=mock_socketio,
            enable_tools=True,
            tool_manager=prebuilt,
        )
        await instance.start()

        prebuilt.load_tools.assert_not_called()
        assert create_graph.call_args.kwargs["tools"] is prebuilt.tools
        assert create_graph.call_args.kwargs["tools_map"] is prebuilt.tools_map


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
    async def test_process_text_injects_trusted_tool_observer_into_run_config(
        self, orchestrator, mock_graph
    ):
        """The observer is server-owned run configuration, never user metadata."""

        observer = object()
        await orchestrator.start()

        await orchestrator.process_text(
            text="完成 Minecraft 任务",
            conversation_id="conversation-showcase-001",
            tool_invocation_observer=observer,
        )

        initial_state = mock_graph.ainvoke.await_args.args[0]
        run_config = mock_graph.ainvoke.await_args.kwargs["config"]
        assert run_config["configurable"]["tool_invocation_observer"] is observer
        assert run_config["configurable"]["effective_tool_invocation_observer"] is not observer
        assert "tool_invocation_observer" not in initial_state["metadata"]

    @pytest.mark.asyncio
    async def test_process_text_can_isolate_one_checkpoint_thread(self, orchestrator, mock_graph):
        checkpoint_runtime = MagicMock()
        checkpoint_runtime.saver.aget_tuple = AsyncMock(return_value=None)
        checkpoint_runtime.delete_thread = AsyncMock()
        orchestrator.checkpoint_runtime = checkpoint_runtime
        await orchestrator.start()

        await orchestrator.process_text(
            text="我回来啦",
            checkpoint_request=CheckpointRequest(
                thread_id="program:run-1:q09",
                owner_kind="program",
                owner_id="run-1",
                retention="stable",
            ),
        )

        run_config = mock_graph.ainvoke.await_args.kwargs["config"]
        assert run_config["configurable"]["thread_id"] == "program:run-1:q09"
        checkpoint_runtime.delete_thread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_plain_chat_does_not_touch_checkpoint_storage(self, orchestrator, mock_graph):
        checkpoint_runtime = MagicMock()
        checkpoint_runtime.health.available = True
        checkpoint_runtime.saver.aget_tuple = AsyncMock(return_value=None)
        checkpoint_runtime.delete_thread = AsyncMock()
        orchestrator.checkpoint_runtime = checkpoint_runtime
        await orchestrator.start()

        result = await orchestrator.process_text(text="普通聊天", task_id="task-plain")

        assert result["response_text"] == "mock reply"
        checkpoint_runtime.saver.aget_tuple.assert_not_awaited()
        checkpoint_runtime.delete_thread.assert_not_awaited()
        assert mock_graph.ainvoke.await_count == 1

    @pytest.mark.asyncio
    async def test_durable_graph_is_compiled_after_redis_recovers(self, orchestrator, mock_graph):
        checkpoint_runtime = MagicMock()
        checkpoint_runtime.health.available = False
        checkpoint_runtime.saver = None
        checkpoint_runtime.delete_thread = AsyncMock()
        orchestrator.checkpoint_runtime = checkpoint_runtime
        await orchestrator.start()
        assert orchestrator.durable_graph is None

        checkpoint_runtime.health.available = True
        checkpoint_runtime.saver = MagicMock()
        checkpoint_runtime.saver.aget_tuple = AsyncMock(return_value=None)

        result = await orchestrator.process_text(
            text="恢复后的长任务",
            checkpoint_request=CheckpointRequest(
                thread_id="program:recovered-run",
                owner_kind="program",
                owner_id="recovered-run",
                retention="stable",
            ),
        )

        assert result["response_text"] == "mock reply"
        assert orchestrator.durable_graph is mock_graph
        checkpoint_runtime.saver.aget_tuple.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_approval_tool_round_migrates_without_second_planning_call(
        self, orchestrator, mock_graph
    ):
        checkpoint_runtime = MagicMock()
        checkpoint_runtime.health.available = True
        checkpoint_runtime.saver.aget_tuple = AsyncMock(return_value=None)
        checkpoint_runtime.delete_thread = AsyncMock()
        orchestrator.checkpoint_runtime = checkpoint_runtime
        mock_graph.ainvoke.side_effect = [
            {
                "task_id": "task-mc",
                "metadata": {"config_hash": "current"},
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "mc_connection",
                        "args": {"operation": "connect"},
                    }
                ],
                "checkpoint_migration_required": True,
            },
            {
                "task_id": "task-mc",
                "response_text": "waiting",
                "checkpoint_migration_required": False,
                "__interrupt__": [SimpleNamespace(value={"approval_id": "approval-1"})],
            },
        ]
        await orchestrator.start()

        result = await orchestrator.process_text(text="连接 Minecraft", task_id="task-mc")

        assert result["approval_required"] == [{"approval_id": "approval-1"}]
        assert mock_graph.ainvoke.await_count == 2
        first_state = mock_graph.ainvoke.await_args_list[0].args[0]
        second_state = mock_graph.ainvoke.await_args_list[1].args[0]
        second_config = mock_graph.ainvoke.await_args_list[1].kwargs["config"]
        assert first_state["user_text"] == "连接 Minecraft"
        assert second_state["tool_calls"][0]["id"] == "call-1"
        assert second_config["configurable"]["thread_id"] == "turn:task-mc"
        assert second_config["configurable"]["history_authority"] == "checkpoint"
        checkpoint_runtime.saver.aget_tuple.assert_awaited_once()
        checkpoint_runtime.delete_thread.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resume_rejects_checkpoint_from_different_runtime_config(
        self, orchestrator, mock_graph
    ):
        checkpoint_runtime = MagicMock()
        checkpoint_runtime.health.available = True
        checkpoint_runtime.saver.aget_tuple = AsyncMock(
            return_value=SimpleNamespace(
                checkpoint={"channel_values": {"metadata": {"config_hash": "old"}}}
            )
        )
        checkpoint_runtime.delete_thread = AsyncMock()
        orchestrator.checkpoint_runtime = checkpoint_runtime
        orchestrator.service_context.runtime_config_hash = "new"
        await orchestrator.start()

        result = await orchestrator.process_text(
            text="resume",
            checkpoint_request=CheckpointRequest(
                thread_id="replay:run-1",
                owner_kind="replay",
                owner_id="run-1",
                retention="stable",
            ),
        )

        assert result["error"] == "CHECKPOINT_CONFIG_MISMATCH"
        mock_graph.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_durable_redis_interruption_returns_stable_error(self, orchestrator, mock_graph):
        from redis.exceptions import ConnectionError as RedisConnectionError

        checkpoint_runtime = MagicMock()
        checkpoint_runtime.health.available = True
        checkpoint_runtime.saver.aget_tuple = AsyncMock(return_value=None)
        checkpoint_runtime.delete_thread = AsyncMock()
        orchestrator.checkpoint_runtime = checkpoint_runtime
        mock_graph.ainvoke.side_effect = RedisConnectionError("offline")
        await orchestrator.start()

        result = await orchestrator.process_text(
            text="resume",
            checkpoint_request=CheckpointRequest(
                thread_id="program:run-1",
                owner_kind="program",
                owner_id="run-1",
                retention="stable",
            ),
        )

        assert result["error"] == "CHECKPOINT_UNAVAILABLE"

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

    @pytest.mark.asyncio
    async def test_shared_livestream_registry_survives_socket_recreation_and_isolates_sessions(
        self, mock_socketio, monkeypatch
    ):
        registry = ConversationSessionRegistry()
        seen_windows: list[tuple[tuple[str, str], ...]] = []

        class CommittingGraph:
            async def ainvoke(self, state, config):
                session = config["configurable"]["conversation_session"]
                seen_windows.append(session.completed_window)
                response = f"reply:{state['user_text']}"
                session.commit(
                    task_id=state["task_id"],
                    user_text=state["user_text"],
                    final_response=response,
                    actor_role=state["metadata"].get("actor_role"),
                    source=state["metadata"].get("source"),
                )
                return {
                    **state,
                    "response_text": response,
                    "response_chunks": [response],
                    "metadata": {
                        **state["metadata"],
                        "conversation_committed": True,
                        "conversation_window_pairs_after": len(session.completed_window),
                    },
                }

        monkeypatch.setattr(
            "animetta.orchestration.graph.orchestrator.get_observability",
            lambda: MagicMock(_initialized=True, callbacks=[]),
        )

        def make_orchestrator(sid: str) -> LangGraphOrchestrator:
            config = MagicMock()
            config.get_persona.return_value = None
            config.get_system_prompt.return_value = "persona"
            config.system.runtime_profile = "development"
            service_context = MagicMock(session_id=sid, config=config)
            instance = LangGraphOrchestrator(
                service_context=service_context,
                socketio=mock_socketio,
                conversation_registry=registry,
            )
            instance.graph = CommittingGraph()
            instance._is_running = True
            return instance

        developer = make_orchestrator("dashboard-socket-before-refresh")
        viewer = make_orchestrator("bilibili-socket")
        refreshed = make_orchestrator("dashboard-socket-after-refresh")

        await developer.process_text(
            "本场暗号是蓝玻璃",
            conversation_id="dashboard-conversation",
            task_id="task-1",
            message_id="message-1",
            turn_id="turn-1",
            audience="livestream",
            live_session_id="live-1",
            actor_role="developer",
            source="developer_console",
        )
        await viewer.process_text(
            "刚才的暗号是什么？",
            conversation_id="danmaku-conversation",
            task_id="task-2",
            message_id="message-2",
            turn_id="turn-2",
            audience="livestream",
            live_session_id="live-1",
            actor_role="viewer",
            source="bilibili:danmaku",
        )
        await refreshed.process_text(
            "上一条弹幕问了什么？",
            conversation_id="dashboard-conversation",
            task_id="task-3",
            message_id="message-3",
            turn_id="turn-3",
            audience="livestream",
            live_session_id="live-1",
            actor_role="developer",
            source="developer_console",
        )
        await refreshed.process_text(
            "新的直播",
            conversation_id="dashboard-conversation",
            task_id="task-4",
            message_id="message-4",
            turn_id="turn-4",
            audience="livestream",
            live_session_id="live-2",
            actor_role="developer",
            source="developer_console",
        )

        assert seen_windows[0] == ()
        assert seen_windows[1] == (("本场暗号是蓝玻璃", "reply:本场暗号是蓝玻璃"),)
        assert seen_windows[2][-1] == ("刚才的暗号是什么？", "reply:刚才的暗号是什么？")
        assert seen_windows[3] == ()


class TestOrchestratorCentralIngressFilter:
    """Defense-in-depth: process_text drops probe-shaped text itself.

    Even if a transport handler forgets to call ``is_probe_messages`` (the
    historical ``desktop.chat_message`` and Bilibili danmaku paths did not),
    a probe-shaped text is dropped here so no caller can route an internal
    probe into the LLM. This is the centralized fix for the transport-bypass
    class of bug (audit P0-1 was one instance).
    """

    @pytest.mark.parametrize(
        "text",
        [
            "ping",
            "PING",
            "  Ping  ",
            "pong",
            "healthcheck",
            "[inspection] secret payload",
            "[health] ok",
            "[probe] 1+1",
            "   ",  # whitespace-only — nothing to say
        ],
    )
    @pytest.mark.asyncio
    async def test_probe_shaped_text_short_circuits_without_graph_run(
        self, orchestrator, mock_graph, text
    ):
        await orchestrator.start()
        mock_graph.ainvoke.reset_mock()

        result = await orchestrator.process_text(text=text)

        # The graph (and therefore the LLM) must never run for a probe.
        mock_graph.ainvoke.assert_not_awaited()
        # No error — the turn is simply dropped.
        assert result.get("error") is None
        assert result["response_text"] == ""
        assert result["response_chunks"] == []

    @pytest.mark.parametrize(
        "text",
        [
            "hello",
            "讲个笑话",
            # A danmaku that happens to contain "ping" as a substring is NOT a
            # bare probe token and must still flow through to the LLM.
            "用户名说: ping",
            "ping 我一下呗",
        ],
    )
    @pytest.mark.asyncio
    async def test_real_text_runs_the_graph(self, orchestrator, mock_graph, text):
        await orchestrator.start()
        mock_graph.ainvoke.reset_mock()

        await orchestrator.process_text(text=text)

        mock_graph.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_probe_short_circuit_preserves_chat_identity(self, orchestrator, mock_graph):
        """Dropped probes still echo the caller-supplied identity fields."""
        await orchestrator.start()
        result = await orchestrator.process_text(
            text="ping",
            message_id="mid",
            conversation_id="cid",
            task_id="tid",
            turn_id="tid",
        )
        assert result["message_id"] == "mid"
        assert result["conversation_id"] == "cid"
        assert result["task_id"] == "tid"
        assert result["turn_id"] == "tid"

    @pytest.mark.asyncio
    async def test_probe_check_happens_after_running_state(self, orchestrator, mock_graph):
        """A probe on a not-started orchestrator returns the not-started error,
        not the probe-drop result — running-state check takes precedence."""
        result = await orchestrator.process_text(text="ping")
        assert "error" in result
        mock_graph.ainvoke.assert_not_awaited()


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
