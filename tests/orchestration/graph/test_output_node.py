from __future__ import annotations

"""Tests for output distribution node — Socket.IO + memory storage."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.types import RunnableConfig

# Note: ``output_node`` resolves to the *function* (re-exported by
# graph/__init__.py), shadowing the module of the same name. To reach
# module-level helpers like ``_is_unpersistable_response`` we go through
# sys.modules to grab the actual module object.
from animetta.observability.context import ObservationContext, observation_context
from animetta.observability.domain import PrivacyMode
from animetta.observability.service_proxy import InstrumentedServiceProxy
from animetta.orchestration.graph import output_node
from animetta.orchestration.graph.media_status import MediaStatus
from animetta.orchestration.graph.state import create_initial_state

_output_node_module = sys.modules["animetta.orchestration.graph.output_node"]


class _OperationRecorder:
    def __init__(self) -> None:
        self.started = []
        self.finished = []
        self.operation_started = asyncio.Event()
        self.operation_finished = asyncio.Event()

    async def start_operation(self, record) -> None:
        self.started.append(record)
        self.operation_started.set()

    async def finish_operation(self, record) -> None:
        self.finished.append(record)
        self.operation_finished.set()

    async def record_event(self, record) -> None:
        del record


class _BlockingTranslationLLM:
    def __init__(self, release: asyncio.Event) -> None:
        self.release = release

    async def chat_messages(self, messages, **kwargs) -> str:
        del messages, kwargs
        await self.release.wait()
        return "translated"


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
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        # Check control signals
        control_calls = [c for c in mock_socketio.emit.call_args_list if c[0][0] == "chat:control"]
        signals = [c[0][1]["signal"] for c in control_calls]
        assert "conversation-start" in signals
        assert "conversation-end" in signals

    @pytest.mark.asyncio
    async def test_emits_text_when_response_exists(self, mock_socketio, mock_service_context):
        """response_text triggers sentence events."""

        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello world"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        sentence_calls = [
            c for c in mock_socketio.emit.call_args_list if c[0][0] == "chat:sentence"
        ]
        assert len(sentence_calls) >= 1
        # First sentence call should have the text
        assert sentence_calls[0][0][1]["text"] == "Hello world"

    @pytest.mark.asyncio
    async def test_pre_emitted_start_and_text_are_not_duplicated_late(
        self, mock_socketio, mock_service_context
    ):
        state = create_initial_state(session_id="test")
        state["response_text"] = "Already delivered"
        state["metadata"] = {
            "conversation_started_at": 1.0,
            "text_ready_at": 2.0,
        }
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )

        await output_node(state, config)

        control_payloads = [
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] == "chat:control"
        ]
        assert [payload.get("signal") for payload in control_payloads] == ["conversation-end"]
        assert not any(
            call.args[0] == "chat:sentence" for call in mock_socketio.emit.call_args_list
        )

    @pytest.mark.asyncio
    async def test_golden_output_never_spends_third_llm_call_on_translation(
        self, mock_socketio, monkeypatch
    ):
        translate = AsyncMock(return_value="translated")
        monkeypatch.setattr(_output_node_module, "translate_subtitle_text", translate)
        monkeypatch.setattr(_output_node_module.translation_state, "enabled", True)
        context = SimpleNamespace(
            config=SimpleNamespace(system=SimpleNamespace(runtime_profile="golden")),
            llm_engine=object(),
            memory_system=None,
        )
        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello world"
        await output_node(
            state,
            RunnableConfig(
                configurable={
                    "socketio": mock_socketio,
                    "service_context": context,
                }
            ),
        )
        translate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_translation_never_emits_after_conversation_end(self, mock_socketio, monkeypatch):
        translate = AsyncMock(return_value="Hello.")
        monkeypatch.setattr(_output_node_module, "translate_subtitle_text", translate)
        monkeypatch.setattr(_output_node_module.translation_state, "enabled", True)
        context = SimpleNamespace(
            config=SimpleNamespace(system=SimpleNamespace(runtime_profile="production")),
            llm_engine=object(),
            memory_system=None,
        )
        state = create_initial_state(session_id="test")
        state["response_text"] = "你好。"

        await output_node(
            state,
            RunnableConfig(
                configurable={
                    "socketio": mock_socketio,
                    "service_context": context,
                }
            ),
        )
        await asyncio.sleep(0)

        events = [call.args[0] for call in mock_socketio.emit.call_args_list]
        assert "chat:subtitle_translation" in events
        assert events.index("chat:subtitle_translation") < max(
            index
            for index, event in enumerate(events)
            if event == "chat:control"
            and mock_socketio.emit.call_args_list[index].args[1].get("signal") == "conversation-end"
        )

    @pytest.mark.asyncio
    async def test_background_translation_service_operation_is_noncritical(
        self, mock_socketio, monkeypatch
    ):
        monkeypatch.setattr(_output_node_module.translation_state, "enabled", True)
        release = asyncio.Event()
        recorder = _OperationRecorder()
        llm = InstrumentedServiceProxy(
            _BlockingTranslationLLM(release),
            recorder,
            "llm",
            provider="test",
            model="test",
        )
        context = SimpleNamespace(
            config=SimpleNamespace(system=SimpleNamespace(runtime_profile="standard")),
            llm_engine=llm,
            memory_system=None,
        )
        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello world"
        root = ObservationContext(
            trace_id=state["task_id"],
            operation_id="output-operation",
            parent_operation_id=None,
            message_id=state["message_id"],
            conversation_id=state["conversation_id"],
            session_id="test",
            privacy_mode=PrivacyMode.FULL,
        )

        with observation_context(root):
            await output_node(
                state,
                RunnableConfig(
                    configurable={
                        "socketio": mock_socketio,
                        "service_context": context,
                        "observation_recorder": recorder,
                    }
                ),
            )

        await asyncio.wait_for(recorder.operation_started.wait(), timeout=1)
        try:
            operation = recorder.started[0]
            assert operation.name == "llm.chat_messages"
            assert operation.critical_path is False
        finally:
            release.set()
            await asyncio.wait_for(recorder.operation_finished.wait(), timeout=1)

    @pytest.mark.asyncio
    async def test_emits_expression_for_emotion(self, mock_socketio, mock_service_context):
        """Emotion in state triggers expression event + Live2D motion."""

        state = create_initial_state(session_id="test")
        state["response_text"] = "I'm happy"
        state["emotion"] = "happy"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        expr_calls = [c for c in mock_socketio.emit.call_args_list if c[0][0] == "chat:expression"]
        assert len(expr_calls) >= 1
        assert expr_calls[0][0][1]["emotion"] == "happy"

        action_calls = [
            c for c in mock_socketio.emit.call_args_list if c[0][0] == "chat:live2d_action"
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
        state["metadata"] = {"dialogue_status": "composer"}
        mock_service_context.config.system.long_term_memory_mode = "read_write"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        # Verify memory storage was called
        mock_service_context.memory_system.encode.assert_called_once()
        call_kwargs = mock_service_context.memory_system.encode.call_args
        assert call_kwargs.kwargs["user_input"] == "Hi there"
        assert call_kwargs.kwargs["agent_response"] == "Hello Alice!"

    @pytest.mark.asyncio
    async def test_shared_runtime_submission_is_non_blocking_and_scoped(
        self, mock_socketio, mock_service_context
    ):
        runtime = MagicMock()
        runtime.submit_turn.return_value = True
        mock_service_context.memory_runtime = runtime
        mock_service_context.memory_system.encode = AsyncMock()
        mock_service_context.config.system.long_term_memory_mode = "read_write"
        state = create_initial_state(
            session_id="socket-a",
            user_text="还记得我吗",
            user_id="bilibili:42",
            channel_id="bilibili",
            conversation_id="22222222-2222-4222-8222-222222222222",
        )
        state["response_text"] = "当然记得。"
        state["metadata"] = {
            "dialogue_status": "composer",
            "channel": "bilibili",
            "stream_id": "bilibili:100",
        }
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )

        await output_node(state, config)

        runtime.submit_turn.assert_called_once()
        turn = runtime.submit_turn.call_args.args[0]
        assert turn.user_input == "还记得我吗"
        assert turn.agent_response == "当然记得。"
        assert turn.context.actor_id == "bilibili:42"
        assert turn.context.conversation_id == "22222222-2222-4222-8222-222222222222"
        assert turn.context.stream_id == "bilibili:100"
        assert turn.context.connection_id == "socket-a"
        mock_service_context.memory_system.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_off_policy_never_encodes_living_memory(
        self, mock_socketio, mock_service_context
    ):
        mock_service_context.memory_system.encode = AsyncMock()
        mock_service_context.config.system.long_term_memory_mode = "off"
        state = create_initial_state(session_id="test", user_text="private")
        state["response_text"] = "final"
        state["metadata"] = {"dialogue_status": "composer"}
        await output_node(
            state,
            RunnableConfig(
                configurable={
                    "socketio": mock_socketio,
                    "service_context": mock_service_context,
                }
            ),
        )
        mock_service_context.memory_system.encode.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_every_success_event_has_one_shared_identity(
        self, mock_socketio, mock_service_context
    ):
        state = create_initial_state(session_id="test")
        state["response_text"] = "Hello"
        state["emotion"] = "happy"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )

        await output_node(state, config)

        golden_events = {
            "chat:control",
            "chat:sentence",
            "chat:expression",
            "chat:live2d_action",
        }
        calls = [
            call for call in mock_socketio.emit.call_args_list if call.args[0] in golden_events
        ]
        assert calls
        expected = {
            "message_id": state["message_id"],
            "conversation_id": state["conversation_id"],
            "task_id": state["task_id"],
            "turn_id": state["task_id"],
        }
        for call in calls:
            payload = call.args[1]
            assert all(payload[field] == value for field, value in expected.items())

    @pytest.mark.asyncio
    async def test_media_failure_emits_correlated_degradation(
        self, mock_socketio, mock_service_context
    ):
        state = create_initial_state(session_id="test")
        state["response_text"] = "Text survives"
        state["tts_audio"] = b"\xff"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )

        await output_node(state, config)

        degradation = next(
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] == "chat:control" and call.args[1].get("status") == "degraded"
        )
        assert degradation["component"] == "tts"
        assert degradation["reason"] == "provider_error"
        assert degradation["task_id"] == state["task_id"]
        assert degradation["turn_id"] == state["task_id"]

    @pytest.mark.asyncio
    async def test_typed_tts_degradation_emits_visible_correlated_control_once(
        self, mock_socketio, mock_service_context
    ):
        state = create_initial_state(session_id="test")
        state["response_text"] = "Text survives"
        state["tts_audio"] = None
        state["media_status"] = MediaStatus(
            "degraded",
            "busy",
            "RemoteTTS",
            True,
        )
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )

        await output_node(state, config)

        degradations = [
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] == "chat:control" and call.args[1].get("type") == "media-degraded"
        ]
        assert len(degradations) == 1
        degradation = degradations[0]
        assert degradation["text"] == "Audio unavailable; continuing with text."
        assert degradation["component"] == "tts"
        assert degradation["reason"] == "rate_limit"
        assert degradation["retryable"] is True
        assert degradation["task_id"] == state["task_id"]
        assert degradation["turn_id"] == state["task_id"]
        assert not any(
            call.args[0] == "chat:audio_with_expression"
            for call in mock_socketio.emit.call_args_list
        )

    @pytest.mark.asyncio
    async def test_legacy_turn_emits_only_declared_legacy_names(
        self, mock_socketio, mock_service_context
    ):
        state = create_initial_state(session_id="test")
        state["response_text"] = "legacy"
        state["metadata"] = {"transport_mode": "legacy"}
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )

        await output_node(state, config)

        event_names = [call.args[0] for call in mock_socketio.emit.call_args_list]
        assert "sentence" in event_names
        assert "control" in event_names
        assert "chat:sentence" not in event_names
        assert "chat:control" not in event_names


class TestUnpersistableResponseGuard:
    """Layer-2 defense: fallback/template replies must not enter V2 memory.

    These replies would otherwise be treated as something Anima actually
    said on the next turn, polluting the persona ("角色污染").
    """

    @pytest.mark.asyncio
    async def test_timeout_fallback_not_stored(self, mock_socketio, mock_service_context):
        """llm_node's FALLBACK_RESPONSE ('I need a moment...') must not persist."""
        mock_service_context.memory_system.encode = AsyncMock()

        state = create_initial_state(
            session_id="test",
            user_text="讲个笑话",
        )
        state["response_text"] = "I need a moment to think about that."
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        mock_service_context.memory_system.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_metadata_flag_not_stored(self, mock_socketio, mock_service_context):
        """When llm_node sets metadata['error_type']='timeout', skip persistence."""
        mock_service_context.memory_system.encode = AsyncMock()

        state = create_initial_state(
            session_id="test",
            user_text="继续",
        )
        # A response that does not match any marker but is flagged as timeout
        state["response_text"] = "[一些部分生成的内容]"
        state["metadata"] = {"error_type": "timeout"}
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        mock_service_context.memory_system.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_mockllm_customer_service_template_not_stored(
        self, mock_socketio, mock_service_context
    ):
        """MockLLM's '有什么我可以帮助你的吗？' template must not persist."""
        mock_service_context.memory_system.encode = AsyncMock()

        state = create_initial_state(
            session_id="test",
            user_text="ping",
        )
        state["response_text"] = "你好！你说的是：「ping」。有什么我可以帮助你的吗？"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        mock_service_context.memory_system.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_mockllm_self_identifying_template_not_stored(
        self, mock_socketio, mock_service_context
    ):
        """MockLLM's '我是一个 Mock LLM' self-identifying template must not persist."""
        mock_service_context.memory_system.encode = AsyncMock()

        state = create_initial_state(
            session_id="test",
            user_text="你是谁",
        )
        state["response_text"] = "收到你的消息：「你是谁」。我是一个 Mock LLM，用于测试和开发。"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        mock_service_context.memory_system.encode.assert_not_called()

    @pytest.mark.asyncio
    async def test_genuine_anima_reply_is_stored(self, mock_socketio, mock_service_context):
        """Real in-character Anima replies must still be persisted.

        Regression guard: the filter must not be over-eager and drop genuine
        conversation turns. Lines containing markers like '帮助' (help) used
        naturally are fine; only the exact customer-service template is dropped.
        """
        mock_service_context.memory_system.encode = AsyncMock()

        state = create_initial_state(
            session_id="test",
            user_text="主播好",
        )
        # An Anima-flavored line that contains 'help' semantically but is
        # clearly in-character — must be persisted.
        state["response_text"] = "又来了。酒馆还没开门你就堵在门口，我帮你倒杯红茶？"
        state["metadata"] = {"dialogue_status": "composer"}
        mock_service_context.config.system.long_term_memory_mode = "read_write"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        mock_service_context.memory_system.encode.assert_called_once()
        call_kwargs = mock_service_context.memory_system.encode.call_args
        assert call_kwargs.kwargs["agent_response"].startswith("又来了")


class TestIsUnpersistableResponse:
    """Unit tests for the _is_unpersistable_response module-level helper."""

    def test_timeout_fallback_marker_detected(self):
        state = create_initial_state(session_id="t")
        state["response_text"] = "I need a moment to think about that."
        assert _output_node_module._is_unpersistable_response(state, state["response_text"]) is True

    def test_customer_service_marker_detected(self):
        state = create_initial_state(session_id="t")
        text = "你好！有什么我可以帮助你的吗？"
        assert _output_node_module._is_unpersistable_response(state, text) is True

    def test_clean_anima_line_passes(self):
        state = create_initial_state(session_id="t")
        text = "……嗯。但我不是很在意天气。"
        assert _output_node_module._is_unpersistable_response(state, text) is False

    def test_timeout_metadata_flag_detected(self):
        state = create_initial_state(session_id="t")
        state["metadata"] = {"error_type": "timeout"}
        assert _output_node_module._is_unpersistable_response(state, "任何内容") is True

    def test_no_timeout_flag_passes(self):
        state = create_initial_state(session_id="t")
        state["metadata"] = {}  # no error_type
        assert _output_node_module._is_unpersistable_response(state, "正常回复") is False


class TestTurnIdentity:
    """Task 1.4: Prove chat:sentence and chat:subtitle_translation payloads
    include matching turn_id."""

    @pytest.mark.asyncio
    async def test_sentence_payload_includes_turn_id(self, mock_socketio, mock_service_context):
        """chat:sentence payload should include turn_id."""
        state = create_initial_state(session_id="test")
        state["response_text"] = "你好"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        sentence_calls = [
            c for c in mock_socketio.emit.call_args_list if c[0][0] == "chat:sentence"
        ]
        # First sentence call should have turn_id
        assert len(sentence_calls) >= 1
        payload = sentence_calls[0][0][1]
        assert "turn_id" in payload
        assert isinstance(payload["turn_id"], str)
        assert len(payload["turn_id"]) > 0

    @pytest.mark.asyncio
    async def test_sentence_and_complete_share_turn_id(self, mock_socketio, mock_service_context):
        """The text sentence and complete marker should share the same turn_id."""
        state = create_initial_state(session_id="test")
        state["response_text"] = "你好"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        sentence_calls = [
            c for c in mock_socketio.emit.call_args_list if c[0][0] == "chat:sentence"
        ]
        assert len(sentence_calls) >= 2
        turn_id_text = sentence_calls[0][0][1].get("turn_id")
        turn_id_complete = sentence_calls[1][0][1].get("turn_id")
        assert turn_id_text == turn_id_complete

    @pytest.mark.asyncio
    async def test_first_class_task_id_overrides_stale_metadata_turn_id(
        self, mock_socketio, mock_service_context
    ):
        """Delivery identity comes from AgentState, never mutable metadata."""
        state = create_initial_state(session_id="test")
        state["response_text"] = "你好"
        state["metadata"] = {"turn_id": "custom_turn_abc"}
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        sentence_calls = [
            c for c in mock_socketio.emit.call_args_list if c[0][0] == "chat:sentence"
        ]
        assert sentence_calls[0][0][1]["turn_id"] == state["task_id"]

    @pytest.mark.asyncio
    async def test_backward_compat_old_fields_preserved(self, mock_socketio, mock_service_context):
        """Existing fields (text, seq, lang) must still be present for old clients."""
        state = create_initial_state(session_id="test")
        state["response_text"] = "你好"
        config = RunnableConfig(
            configurable={
                "socketio": mock_socketio,
                "service_context": mock_service_context,
            }
        )
        await output_node(state, config)

        sentence_calls = [
            c for c in mock_socketio.emit.call_args_list if c[0][0] == "chat:sentence"
        ]
        payload = sentence_calls[0][0][1]
        # Old fields must still be present
        assert "text" in payload
        assert "seq" in payload
        assert "lang" in payload
        # New field added
        assert "turn_id" in payload
