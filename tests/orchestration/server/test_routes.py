from __future__ import annotations

"""Tests for WebSocket route handlers — event dispatch and registration."""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from animetta.orchestration.chat_contracts import ChatTransportMode, ChatTurnCommand
from animetta.orchestration.server.desktop import DesktopClientManager
from animetta.orchestration.server.live2d import Live2DManager
from animetta.orchestration.server.routes import RouteHandlers, register_routes

# ── Helper fixture ─────────────────────────────────────────────────


@pytest.fixture
def mock_session_manager():
    """Mock SessionManager with async methods."""
    sm = MagicMock()
    sm.get_or_create_context = AsyncMock(return_value=MagicMock())
    sm.get_or_create_orchestrator = AsyncMock(return_value=MagicMock())
    sm.get_or_create_audio_processor = AsyncMock(return_value=MagicMock())
    sm.get_audio_processor = MagicMock(return_value=MagicMock())
    sm.get_context = MagicMock(return_value=MagicMock())
    sm.get_orchestrator = MagicMock()
    sm.cleanup_session = AsyncMock()
    return sm


# ── RouteHandlers — Init ───────────────────────────────────────────


class TestRouteHandlersInit:
    """RouteHandlers construction and default attributes."""

    def test_init_sets_attributes(self, mock_socketio, mock_session_manager):
        """__init__ stores references and creates default managers."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        assert handlers.sio is mock_socketio
        assert handlers.session_manager is mock_session_manager
        assert handlers.desktop_manager is not None
        assert handlers.live2d_manager is not None
        assert handlers._bilibili_service is None
        assert handlers._main_loop is None
        assert handlers.global_config is None
        assert handlers.user_settings is None

    def test_init_with_explicit_managers(self, mock_socketio, mock_session_manager):
        """Explicit desktop_manager and live2d_manager are used."""
        dcm = DesktopClientManager()
        l2d = Live2DManager()
        handlers = RouteHandlers(mock_socketio, mock_session_manager,
                                 desktop_manager=dcm, live2d_manager=l2d)
        assert handlers.desktop_manager is dcm
        assert handlers.live2d_manager is l2d

    def test_set_global_config(self, mock_socketio, mock_session_manager):
        """set_global_config stores and propagates the config."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        config = MagicMock()
        handlers.set_global_config(config)
        assert handlers.global_config is config
        assert handlers.base.global_config is config
        assert handlers.chat.global_config is config
        assert handlers.persona.global_config is config

    def test_global_config_assignment_updates_shared_base(
        self, mock_socketio, mock_session_manager
    ):
        """Backward-compatible direct assignment updates shared handler state."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        config = MagicMock()

        handlers.global_config = config

        assert handlers.base.global_config is config
        assert handlers.config_handlers.global_config is config

    def test_persona_config_logging_does_not_leak_config_repr(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """Persona handler config plumbing must not log the full config object."""

        class SecretConfig:
            persona = "anima"

            def __repr__(self) -> str:
                return "SecretConfig(api_key='sk-test-secret')"

        info = MagicMock()
        debug = MagicMock()
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.persona_handlers.logger.info",
            info,
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.persona_handlers.logger.debug",
            debug,
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.set_global_config(SecretConfig())
        _ = handlers.persona.global_config

        logged = "\n".join(
            str(call.args) + str(call.kwargs)
            for log in (info, debug)
            for call in log.call_args_list
        )
        assert "sk-test-secret" not in logged

    def test_set_user_settings(self, mock_socketio, mock_session_manager):
        """set_user_settings stores settings reference."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        settings = MagicMock()
        handlers.set_user_settings(settings)
        assert handlers.user_settings is settings

    def test_user_settings_assignment_updates_shared_base(
        self, mock_socketio, mock_session_manager
    ):
        """Backward-compatible direct assignment updates shared user settings."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        settings = MagicMock()

        handlers.user_settings = settings

        assert handlers.base.user_settings is settings
        assert handlers.config_handlers.user_settings is settings

    def test_memory_events_are_owned_by_memory_handler(
        self, mock_socketio, mock_session_manager
    ):
        """RouteHandlers remains a facade for memory/wiki events."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        assert handlers.memory.global_config is handlers.global_config

    def test_meme_events_are_owned_by_meme_handler(
        self, mock_socketio, mock_session_manager
    ):
        """RouteHandlers remains a facade for meme review events."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        assert handlers.meme is not None

    def test_setup_live2d_callback_sets_execute_callback(self, mock_socketio, mock_session_manager):
        """_setup_live2d_callback registers an async callback on the Live2D manager."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        assert handlers.live2d_manager._execute_callback is not None

    @pytest.mark.asyncio
    async def test_base_exposes_public_send_callback(
        self, mock_socketio, mock_session_manager
    ):
        """Routes should use the public callback factory, not private helpers."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        send_callback = handlers.base.make_send_callback("sid1")
        await send_callback({"type": "chat:sentence", "text": "hello"})

        mock_socketio.emit.assert_called_once_with(
            "chat:sentence",
            {"type": "chat:sentence", "text": "hello"},
            to="sid1",
        )

    @pytest.mark.asyncio
    async def test_base_orchestrator_reuses_context_send_callback(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """Context and orchestrator setup should share the same send callback."""
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.base_handler.get_live2d_config",
            MagicMock(return_value=MagicMock()),
        )
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.set_global_config(MagicMock())
        ctx = MagicMock()
        orchestrator = MagicMock()
        mock_session_manager.get_or_create_context = AsyncMock(return_value=ctx)
        mock_session_manager.get_or_create_orchestrator = AsyncMock(
            return_value=orchestrator
        )
        mock_session_manager.get_or_create_audio_processor = AsyncMock()

        await handlers.base._get_or_create_orchestrator("sid1")

        context_callback = mock_session_manager.get_or_create_context.await_args.args[2]
        orchestrator_callback = (
            mock_session_manager.get_or_create_orchestrator.await_args.args[2]
        )
        assert context_callback is orchestrator_callback


# ── RouteHandlers — Handler dispatch ───────────────────────────────


class TestRouteHandlersDispatch:
    """Core handler methods: text, audio, interrupt."""

    @pytest.mark.asyncio
    async def test_on_text_input_calls_orchestrator(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """on_text_input gets orchestrator and calls process_text."""
        mock_orch = AsyncMock()
        mock_orch.process_text = AsyncMock()
        mock_session_manager.get_or_create_orchestrator = AsyncMock(return_value=mock_orch)

        monkeypatch.setattr("animetta.config.AppConfig.load", MagicMock)
        monkeypatch.setattr("animetta.config.live2d.get_live2d_config", lambda: MagicMock())

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()

        await handlers.on_text_input("sid1", {"text": "hello", "user_id": "user1"})

        mock_orch.process_text.assert_called_once()
        _, kwargs = mock_orch.process_text.call_args
        assert kwargs["text"] == "hello"
        assert kwargs["user_id"] == "local:user1"
        assert kwargs["channel"] == "local"
        UUID(kwargs["conversation_id"])

    @pytest.mark.asyncio
    async def test_on_text_input_handles_explicit_zhouli_without_orchestrator(
        self, mock_socketio, mock_session_manager
    ):
        """meme:zhouli should be handled as a style tool command before LLM dispatch."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()
        mock_orch = AsyncMock()
        mock_session_manager.get_or_create_orchestrator = AsyncMock(return_value=mock_orch)

        await handlers.on_text_input("sid1", {"text": "meme:zhouli 今天不想上班"})

        mock_session_manager.get_or_create_orchestrator.assert_not_called()
        mock_orch.process_text.assert_not_called()
        control_payloads = [
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] == "chat:control"
        ]
        assert control_payloads[0]["signal"] == "conversation-start"
        sentence_payloads = [
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] == "chat:sentence" and call.args[1].get("text")
        ]
        assert sentence_payloads
        assert "今天不想上班" in sentence_payloads[0]["text"]
        assert "此岂不合乎周礼？" in sentence_payloads[0]["text"]
        metadata = sentence_payloads[0]["metadata"]
        assert metadata["response_plan"]["effects"][0]["id"] == "meme:zhouli"
        assert metadata["effects"][0]["format_id"] == "zhouli"
        assert {event["type"] for event in metadata["effect_events"]} >= {
            "voice",
            "face",
            "overlay",
        }
        assert control_payloads[-1]["signal"] == "conversation-end"
        identity = {
            field: sentence_payloads[0][field]
            for field in ("message_id", "conversation_id", "task_id", "turn_id")
        }
        assert identity["turn_id"] == identity["task_id"]
        for payload in (*control_payloads, *sentence_payloads):
            assert all(payload[field] == value for field, value in identity.items())

    @pytest.mark.asyncio
    async def test_on_text_input_empty_text_returns_early(
        self, mock_socketio, mock_session_manager
    ):
        """Empty text should skip orchestrator call."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()
        mock_orch = AsyncMock()
        mock_session_manager.get_or_create_orchestrator = AsyncMock(return_value=mock_orch)
        mock_session_manager.get_or_create_context = AsyncMock(return_value=MagicMock())
        mock_session_manager.get_or_create_audio_processor = AsyncMock(return_value=MagicMock())

        await handlers.on_text_input("sid1", {"text": ""})
        mock_orch.process_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_text_input_error_emits_error(
        self, mock_socketio, mock_session_manager
    ):
        """Exception during text processing emits error event."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()
        mock_session_manager.get_or_create_orchestrator = AsyncMock(
            side_effect=RuntimeError("test error")
        )

        await handlers.on_text_input("sid1", {"text": "hello"})

        error_payload = next(
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] == "system:error"
        )
        assert error_payload["type"] == "internal_error"
        assert error_payload["message"] == "test error"
        assert error_payload["turn_id"] == error_payload["task_id"]

    @pytest.mark.asyncio
    async def test_on_switch_config_accepts_catalog_config_name(
        self, mock_socketio, mock_session_manager
    ):
        """config:switch should use the catalog payload field."""

        mock_session_manager.orchestrators = {"sid1": MagicMock()}
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_switch_config("sid1", {"config_name": "streaming"})

        assert "sid1" not in mock_session_manager.orchestrators
        mock_socketio.emit.assert_any_call(
            "config:switched",
            {
                "type": "config:switched",
                "config_name": "streaming",
                "message": "Switched to config: streaming",
            },
            to="sid1",
        )

    @pytest.mark.asyncio
    async def test_on_set_log_level_emits_success_response(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """config:log_level should report success state and persisted level."""

        set_level = MagicMock(return_value=True)
        get_level = MagicMock(return_value="DEBUG")
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.config_handlers.logger_manager.set_level",
            set_level,
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.config_handlers.logger_manager.get_level",
            get_level,
        )
        settings = MagicMock()
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.set_user_settings(settings)

        await handlers.on_set_log_level("sid1", {"level": "debug"})

        set_level.assert_called_once_with("DEBUG")
        settings.set_log_level.assert_called_once_with("DEBUG")
        mock_socketio.emit.assert_any_call(
            "config:log_level_changed",
            {
                "type": "config:log_level_changed",
                "success": True,
                "level": "DEBUG",
                "message": "Log level set to DEBUG",
            },
            to="sid1",
        )

    @pytest.mark.asyncio
    async def test_on_raw_audio_data_processes_chunk(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """on_raw_audio_data sends audio chunk to processor."""
        mock_processor = AsyncMock()
        mock_processor.process_chunk = AsyncMock()
        mock_session_manager.get_audio_processor.return_value = mock_processor

        monkeypatch.setattr("animetta.config.AppConfig.load", MagicMock)
        monkeypatch.setattr("animetta.config.live2d.get_live2d_config", lambda: MagicMock())

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()

        await handlers.on_raw_audio_data("sid1", {"audio": [0.1, 0.2, 0.3]})

        mock_processor.process_chunk.assert_called_once_with([0.1, 0.2, 0.3])

    @pytest.mark.asyncio
    async def test_on_raw_audio_data_empty_returns_early(
        self, mock_socketio, mock_session_manager
    ):
        """Empty audio data returns without calling processor."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        mock_processor = MagicMock()
        mock_session_manager.get_audio_processor.return_value = mock_processor

        await handlers.on_raw_audio_data("sid1", {"audio": []})
        mock_processor.process_chunk.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_mic_audio_end_calls_process_end(
        self, mock_socketio, mock_session_manager
    ):
        """on_mic_audio_end calls processor.process_end()."""
        mock_processor = AsyncMock()
        mock_processor.process_end = AsyncMock()
        mock_session_manager.get_audio_processor.return_value = mock_processor

        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_mic_audio_end("sid1", {})

        mock_processor.process_end.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_mic_audio_end_no_processor_logs(
        self, mock_socketio, mock_session_manager
    ):
        """on_mic_audio_end handles missing processor gracefully."""
        mock_session_manager.get_audio_processor.return_value = None

        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_mic_audio_end("sid1", {})

    @pytest.mark.asyncio
    async def test_on_interrupt_signal_sets_interrupt_and_emits(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """on_interrupt_signal calls interrupt handler and emits stop/control events."""
        mock_interrupt = MagicMock()
        mock_interrupt_handler = MagicMock(return_value=mock_interrupt)
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.chat_handlers.get_interrupt_handler",
            mock_interrupt_handler,
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_interrupt_signal("sid1", {"text": "stop please"})

        mock_interrupt.set_interrupt.assert_called_once_with("sid1")
        stop_payload = next(
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] == "chat:stop_audio"
        )
        control_payload = next(
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] == "chat:control"
        )
        assert control_payload["type"] == "control"
        assert control_payload["text"] == "interrupted"
        for field in ("message_id", "conversation_id", "task_id", "turn_id"):
            assert stop_payload[field] == control_payload[field]

    @pytest.mark.asyncio
    async def test_on_get_config_lists_project_personas(
        self, mock_socketio, mock_session_manager
    ):
        """config:get should list personas from the project config directory."""

        config = SimpleNamespace(
            persona="default",
            services=SimpleNamespace(
                asr="mock",
                tts="mock",
                agent="mock",
                vad="mock",
            ),
            asr=SimpleNamespace(type="mock"),
            tts=SimpleNamespace(type="mock"),
            agent=SimpleNamespace(llm_config=SimpleNamespace(type="mock")),
            vad=SimpleNamespace(type="mock"),
            system=SimpleNamespace(host="localhost", port=12394, log_level="INFO"),
        )
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.set_global_config(config)

        await handlers.on_get_config("sid1", {})

        payload = None
        for call_args in mock_socketio.emit.call_args_list:
            if call_args.args[0] == "config:data":
                payload = call_args.args[1]
                break

        assert payload is not None
        assert "default" in payload["available_personas"]

    @pytest.mark.asyncio
    async def test_on_get_config_uses_shared_active_config_boundary(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """config:get should use BaseSocketHandler config fallback in one place."""

        config = SimpleNamespace(
            persona="default",
            services=SimpleNamespace(
                asr="mock",
                tts="mock",
                agent="mock",
                vad="mock",
            ),
            asr=SimpleNamespace(type="mock"),
            tts=SimpleNamespace(type="mock"),
            agent=SimpleNamespace(llm_config=SimpleNamespace(type="mock")),
            vad=SimpleNamespace(type="mock"),
            system=SimpleNamespace(host="localhost", port=12394, log_level="INFO"),
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.config_handlers.get_live2d_config",
            MagicMock(return_value=SimpleNamespace(model=SimpleNamespace(path="/model.json"))),
        )
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.config_handlers.get_active_config = MagicMock(return_value=config)

        await handlers.on_get_config("sid1", {})

        handlers.config_handlers.get_active_config.assert_called_once_with()
        mock_socketio.emit.assert_any_call(
            "config:data",
            {
                "persona": "default",
                "services": {
                    "asr": "mock",
                    "tts": "mock",
                    "agent": "mock",
                    "vad": "mock",
                },
                "active_services": {
                    "asr": "mock",
                    "tts": "mock",
                    "llm": "mock",
                    "vad": "mock",
                },
                "system": {
                    "host": "localhost",
                    "port": 12394,
                    "log_level": "INFO",
                },
                "live2d": {
                    "model_path": "/model.json",
                    "enabled": True,
                },
                "available_personas": ANY,
            },
            to="sid1",
        )

    @pytest.mark.asyncio
    async def test_bilibili_ai_reply_uses_current_service_context_config(
        self, mock_socketio, mock_session_manager
    ):
        """Bilibili reply integration should use ServiceContext.config directly."""

        persona = SimpleNamespace(name="Anima")
        config = MagicMock()
        config.get_persona.return_value = persona
        service_context = SimpleNamespace(config=config)
        orchestrator = SimpleNamespace(
            service_context=service_context,
            process_text=AsyncMock(
                return_value={
                    "response_text": "hello back",
                    "emotion": None,
                    "tts_audio": None,
                }
            ),
        )
        message = SimpleNamespace(
            text="hello",
            user_name="viewer",
            user_id=1001,
            to_dict=lambda: {
                "text": "hello",
                "user_name": "viewer",
                "user_id": 1001,
            },
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.base._get_or_create_orchestrator = AsyncMock(return_value=orchestrator)

        await handlers.bilibili._process_danmaku(message)

        process_kwargs = orchestrator.process_text.await_args.kwargs
        assert process_kwargs["turn_id"] == process_kwargs["task_id"]
        assert process_kwargs["user_id"] == "bilibili:1001"
        assert process_kwargs["channel"] == "bilibili"
        golden_payloads = [
            call.args[1]
            for call in mock_socketio.emit.call_args_list
            if call.args[0] in {"chat:control", "chat:sentence"}
        ]
        assert golden_payloads
        for payload in golden_payloads:
            for field in ("message_id", "conversation_id", "task_id", "turn_id"):
                assert payload[field] == process_kwargs[field]

        reply_payload = None
        for call_args in mock_socketio.emit.call_args_list:
            if call_args.args[0] == "bilibili:danmaku_ai_reply":
                reply_payload = call_args.args[1]
                break

        assert reply_payload is not None
        assert reply_payload["danmaku_text"] == "hello"
        assert reply_payload["reply_text"] == "hello back"
        assert reply_payload["user_name"] == "viewer"
        assert reply_payload["character_name"] == "Anima"
        assert isinstance(reply_payload["timestamp"], float)

    @pytest.mark.asyncio
    async def test_translation_configure_updates_shared_translation_state(
        self, mock_socketio, mock_session_manager
    ):
        """translation:configure should update the shared translation state."""

        from animetta.orchestration.graph.translation_state import translation_state

        old_target = translation_state.target_language
        old_enabled = translation_state.enabled
        try:
            handlers = RouteHandlers(mock_socketio, mock_session_manager)

            await handlers.on_translation_configure(
                "sid1", {"target_language": "Japanese", "enabled": False}
            )

            assert translation_state.target_language == "Japanese"
            assert translation_state.enabled is False
            mock_socketio.emit.assert_any_call(
                "translation:status",
                {"target_language": "Japanese", "enabled": False},
                to="sid1",
            )
        finally:
            translation_state.target_language = old_target
            translation_state.enabled = old_enabled

    @pytest.mark.asyncio
    async def test_on_set_persona_uses_current_context_config(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """Persona switching should use ServiceContext.config directly."""

        from animetta.config.persona import PersonaConfig

        new_persona = SimpleNamespace(personality=None)
        monkeypatch.setattr(PersonaConfig, "load", MagicMock(return_value=new_persona))
        monkeypatch.setattr(
            "animetta.config.live2d.get_live2d_config",
            MagicMock(return_value=SimpleNamespace(enabled=False)),
        )

        llm = MagicMock()
        config = MagicMock()
        config.get_system_prompt.return_value = "new prompt"
        ctx = SimpleNamespace(llm_engine=llm, config=config)
        mock_session_manager.get_context.return_value = ctx
        mock_session_manager.get_orchestrator.return_value = MagicMock()

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.set_global_config(config)

        await handlers.on_set_persona("sid1", {"persona_name": "anima"})

        llm.set_system_prompt.assert_called_once_with("new prompt")
        mock_socketio.emit.assert_any_call(
            "persona:updated",
            {"persona_name": "anima", "mbti": None},
            to="sid1",
        )

    @pytest.mark.asyncio
    async def test_on_set_personality_mode_emits_mode_response(
        self, mock_socketio, mock_session_manager
    ):
        """persona:set_mode should emit the selected personality mode."""

        orchestrator = SimpleNamespace()
        mock_session_manager.get_orchestrator.return_value = orchestrator
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_set_personality_mode("sid1", {"mode": "streaming"})

        assert orchestrator._personality_mode == {"mode": "streaming"}
        mock_socketio.emit.assert_any_call(
            "persona:personality_updated",
            {"mode": "streaming"},
            to="sid1",
        )

    @pytest.mark.asyncio
    async def test_on_get_available_personas_uses_active_config_persona_cache(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """persona:list should read MBTI from the active AppConfig persona cache."""

        mbti = SimpleNamespace(
            type="INTJ",
            dimensions=SimpleNamespace(ei=20, sn=80, tf=75, jp=65),
            description="cached profile",
        )
        current_persona = SimpleNamespace(
            personality=SimpleNamespace(mbti=mbti),
        )
        config = SimpleNamespace(
            persona="anima",
            get_persona=MagicMock(return_value=current_persona),
        )
        direct_load = MagicMock(side_effect=RuntimeError("direct load should not run"))

        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.persona_handlers.list_available_personas",
            MagicMock(return_value=["anima"]),
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.persona_handlers.PersonaConfig.load",
            direct_load,
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.set_global_config(config)

        result = await handlers.on_get_available_personas("sid1", {})

        config.get_persona.assert_called_once_with()
        direct_load.assert_not_called()
        assert result == {
            "personas": ["anima"],
            "current_persona": "anima",
            "mbti": {
                "type": "INTJ",
                "dimensions": {"ei": 20, "sn": 80, "tf": 75, "jp": 65},
                "description": "cached profile",
            },
        }

    @pytest.mark.asyncio
    async def test_on_get_available_personas_logging_does_not_leak_config_repr(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """persona:list diagnostics must not log the full config object."""

        class SecretConfig:
            persona = "anima"

            def get_persona(self):
                return SimpleNamespace(personality=None)

            def __repr__(self) -> str:
                return "SecretConfig(api_key='sk-persona-list-secret')"

        info = MagicMock()
        debug = MagicMock()
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.persona_handlers.logger.info",
            info,
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.persona_handlers.logger.debug",
            debug,
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.persona_handlers.list_available_personas",
            MagicMock(return_value=["anima"]),
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.set_global_config(SecretConfig())

        result = await handlers.on_get_available_personas("sid1", {})

        assert result == {
            "personas": ["anima"],
            "current_persona": "anima",
            "mbti": None,
        }
        logged = "\n".join(
            str(call.args) + str(call.kwargs)
            for log in (info, debug)
            for call in log.call_args_list
        )
        assert "sk-persona-list-secret" not in logged

    @pytest.mark.asyncio
    async def test_on_memory_organize_uses_public_metabolism_api(
        self, mock_socketio, mock_session_manager
    ):
        """memory:organize should not reach into MemorySystem private methods."""

        class PublicMemorySystem:
            def __init__(self) -> None:
                self.tick_called = False
                self.store = SimpleNamespace(get_revision=AsyncMock(return_value=4))

            async def run_metabolism_tick(self) -> None:
                self.tick_called = True

        memory = PublicMemorySystem()
        mock_session_manager.get_or_create_context = AsyncMock(
            return_value=SimpleNamespace(memory_system=memory)
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()

        accepted = await handlers.on_memory_organize("sid1", {})
        job_id = accepted["data"]["job_id"]
        await handlers.memory.wait_for_job(job_id)

        assert memory.tick_called
        mock_socketio.emit.assert_any_call(
            "memory:organize_result",
            {
                "job_id": job_id,
                "status": "completed",
                "progress": 100,
                "revision": 4,
                "message": "Memory organized",
            },
            to="sid1",
        )

    @pytest.mark.asyncio
    async def test_on_get_wiki_pages_uses_public_memory_api(
        self, mock_socketio, mock_session_manager
    ):
        """memory:list_pages should not reach through MemorySystem into its store."""

        pages = [{
            "path": "raw-1",
            "title": "Latte",
            "content": "用户: 我喜欢拿铁",
            "page_type": "source",
            "tags": ["s1"],
            "updated_at": "2026-07-06T00:00:00+00:00",
        }]

        class PublicMemorySystem:
            store = SimpleNamespace(get_revision=AsyncMock(return_value=7))

            async def list_wiki_pages(self, limit: int = 50) -> list[dict]:
                assert limit == 50
                return pages

        mock_session_manager.get_or_create_context = AsyncMock(
            return_value=SimpleNamespace(memory_system=PublicMemorySystem())
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()

        assert await handlers.on_get_wiki_pages("sid1", {}) == {
            "pages": pages,
            "revision": 7,
        }

    @pytest.mark.asyncio
    async def test_meme_review_roundtrip_uses_registered_runtime_pool(
        self, mock_socketio, mock_session_manager
    ):
        """meme:* events should back the frontend review workflow."""

        mock_session_manager.get_or_create_context = AsyncMock(
            return_value=SimpleNamespace(llm_engine=None)
        )
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        add_result = await handlers.on_add_meme(
            "sid1",
            {
                "text": "电子榨菜",
                "source": "user",
                "tags": ["bilibili"],
                "format_id": "zhouli",
                "format_slots": {"modern_event": "想吃电子榨菜"},
                "format_confidence": 0.8,
                "rendered_text": "吾闻古人佐餐，此岂不合乎周礼？",
                "mode": "quip",
            },
        )
        meme_id = add_result["meme"]["id"]

        list_result = await handlers.on_list_memes("sid1", {"limit": 50})
        review_result = await handlers.on_review_meme(
            "sid1", {"meme_id": meme_id, "status": "good"}
        )
        dataset_result = await handlers.on_export_meme_dataset("sid1", {})

        assert add_result["ok"] is True
        assert list_result["memes"][0]["text"] == "电子榨菜"
        assert list_result["memes"][0]["format_id"] == "zhouli"
        assert list_result["memes"][0]["format_slots"] == {"modern_event": "想吃电子榨菜"}
        assert review_result == {"ok": True, "feedback": "已收录为好梗"}
        assert dataset_result["memes"][0]["review_status"] == "good"
        assert dataset_result["memes"][0]["format_id"] == "zhouli"
        mock_socketio.emit.assert_any_call("meme:list", list_result, to="sid1")
        mock_socketio.emit.assert_any_call("meme:review", review_result, to="sid1")
        mock_socketio.emit.assert_any_call("meme:dataset", dataset_result, to="sid1")


# ── RouteHandlers — Broadcast ──────────────────────────────────────


class TestRouteHandlersBroadcast:
    """Broadcast to desktop clients."""

    @pytest.mark.asyncio
    async def test_broadcast_to_desktop_clients_sends_to_each_sid(
        self, mock_socketio, mock_session_manager
    ):
        """broadcast_to_desktop_clients emits to all matching SIDs."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.desktop_manager.clients = {
            "sid_a": {"client_type": "live2d", "connected": True},
            "sid_b": {"client_type": "live2d", "connected": True},
        }

        await handlers.broadcast_to_desktop_clients("live2d", "live2d.action", {"foo": "bar"})

        assert mock_socketio.emit.call_count == 2
        mock_socketio.emit.assert_any_call("live2d.action", {"foo": "bar"}, to="sid_a")
        mock_socketio.emit.assert_any_call("live2d.action", {"foo": "bar"}, to="sid_b")


# ── RouteHandlers — Connection events ──────────────────────────────


class TestRouteHandlersConnection:
    """Connection and disconnection handlers."""

    @pytest.mark.asyncio
    async def test_on_connect_saves_session_and_emits(
        self, mock_socketio, mock_session_manager
    ):
        """on_connect saves session and emits connection-established."""
        mock_socketio.save_session = AsyncMock()
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_connect("sid1", {"HTTP_USER_AGENT": "Mozilla/5.0"})

        mock_socketio.save_session.assert_called_once()
        # Check emitted event structure without asserting exact time
        found = False
        for call_args in mock_socketio.emit.call_args_list:
            if call_args[0][0] == "system:connection_established":
                data = call_args[0][1]
                assert data["message"] == "Connection successful"
                assert data["sid"] == "sid1"
                assert isinstance(data["server_time"], float)
                found = True
        assert found, "system:connection_established event was not emitted"

    @pytest.mark.asyncio
    async def test_on_connect_electron_no_start_mic(
        self, mock_socketio, mock_session_manager
    ):
        """Electron clients should NOT get start-mic signal."""
        mock_socketio.save_session = AsyncMock()
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_connect("sid1", {"HTTP_USER_AGENT": "Electron/10.0"})

        # Check no control event with start-mic
        for call_args in mock_socketio.emit.call_args_list:
            if call_args[0][0] == "chat:control":
                assert call_args[0][1].get("text") != "start-mic"

    @pytest.mark.asyncio
    async def test_on_disconnect_cleans_up(
        self, mock_socketio, mock_session_manager
    ):
        """on_disconnect unregisters client and cleans up session."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_disconnect("sid1")

        mock_session_manager.cleanup_session.assert_called_once_with("sid1")


# ── register_routes ────────────────────────────────────────────────


class TestRegisterRoutes:
    """register_routes function binds events to handler methods."""

    async def test_registered_chat_text_reaches_orchestrator(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        """A normal chat:text payload should traverse the registered route cleanly."""
        mock_orchestrator = AsyncMock()
        mock_orchestrator.process_text = AsyncMock(return_value={})
        mock_session_manager.get_or_create_orchestrator = AsyncMock(
            return_value=mock_orchestrator
        )
        chat_logger = MagicMock()

        monkeypatch.setattr("animetta.config.AppConfig.load", MagicMock)
        monkeypatch.setattr(
            "animetta.config.live2d.get_live2d_config", lambda: MagicMock()
        )
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.chat_handlers.logger",
            chat_logger,
        )
        handlers = register_routes(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()
        chat_text_handler = next(
            call.args[1]
            for call in mock_socketio.on.call_args_list
            if call.args[0] == "chat:text"
        )

        await chat_text_handler(
            "sid1",
            {
                "text": "hello",
                "user_id": "user1",
                "from_name": "User",
                "message_id": str(uuid4()),
                "conversation_id": str(uuid4()),
                "task_id": str(uuid4()),
            },
        )

        mock_orchestrator.process_text.assert_awaited_once_with(
            text="hello",
            user_id="local:user1",
            user_name="User",
            channel_id="sid1",
            message_id=ANY,
            conversation_id=ANY,
            task_id=ANY,
            turn_id=ANY,
            transport_mode="canonical",
            channel="local",
        )
        undefined_helper_logs = [
            str(call.args[0])
            for call in chat_logger.debug.call_args_list
            if "not defined" in str(call.args[0])
        ]
        assert undefined_helper_logs == []

    def test_register_routes_binds_events(self, mock_socketio, mock_session_manager):
        """register_routes calls sio.on() for every event."""
        handlers = register_routes(mock_socketio, mock_session_manager)

        assert isinstance(handlers, RouteHandlers)
        # sio.on should have been called many times
        assert mock_socketio.on.call_count >= 10

    def test_register_routes_binds_connect_and_disconnect(
        self, mock_socketio, mock_session_manager
    ):
        """connect and disconnect events are bound."""
        register_routes(mock_socketio, mock_session_manager)

        events_bound = {call.args[0] for call in mock_socketio.on.call_args_list}
        assert "connect" in events_bound
        assert "disconnect" in events_bound

    def test_register_routes_binds_conversation_events(
        self, mock_socketio, mock_session_manager
    ):
        """Key conversation events are bound."""
        register_routes(mock_socketio, mock_session_manager)

        events_bound = {call.args[0] for call in mock_socketio.on.call_args_list}
        for event in ("chat:text", "chat:audio", "chat:audio_end", "chat:interrupt"):
            assert event in events_bound, f"{event} should be registered"

    @pytest.mark.asyncio
    async def test_catalog_text_aliases_share_one_normalized_command_handler(
        self, mock_socketio, mock_session_manager
    ):
        handlers = register_routes(mock_socketio, mock_session_manager)
        handlers.chat.on_text_command = AsyncMock()
        registered = {
            call.args[0]: call.args[1] for call in mock_socketio.on.call_args_list
        }
        identity = {
            "message_id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "task_id": str(uuid4()),
        }

        await registered["chat:text"]("canonical-sid", {"text": "hello", **identity})
        await registered["text_input"]("legacy-sid", {"text": "legacy"})

        assert handlers.chat.on_text_command.await_count == 2
        canonical = handlers.chat.on_text_command.await_args_list[0].args
        legacy = handlers.chat.on_text_command.await_args_list[1].args
        assert canonical[0] == "canonical-sid"
        assert isinstance(canonical[1], ChatTurnCommand)
        assert canonical[1].transport_mode is ChatTransportMode.CANONICAL
        assert legacy[0] == "legacy-sid"
        assert isinstance(legacy[1], ChatTurnCommand)
        assert legacy[1].transport_mode is ChatTransportMode.LEGACY

    def test_text_alias_registration_is_catalog_backed(
        self, mock_socketio, mock_session_manager, monkeypatch
    ):
        monkeypatch.setitem(
            __import__(
                "animetta.orchestration.socket_events", fromlist=["EVENTS"]
            ).EVENTS["chat"]["text"],
            "aliases",
            ["legacy_chat_input"],
        )

        register_routes(mock_socketio, mock_session_manager)

        events_bound = {call.args[0] for call in mock_socketio.on.call_args_list}
        assert "legacy_chat_input" in events_bound
        assert "text_input" not in events_bound

    def test_register_routes_binds_meme_events(
        self, mock_socketio, mock_session_manager
    ):
        """Meme review catalog events are bound to backend handlers."""
        register_routes(mock_socketio, mock_session_manager)

        events_bound = {call.args[0] for call in mock_socketio.on.call_args_list}
        for event in ("meme:add", "meme:list", "meme:review", "meme:dataset", "meme:collect"):
            assert event in events_bound, f"{event} should be registered"

    def test_register_routes_binds_desktop_events(
        self, mock_socketio, mock_session_manager
    ):
        """Desktop client events are bound."""
        register_routes(mock_socketio, mock_session_manager)

        events_bound = {call.args[0] for call in mock_socketio.on.call_args_list}
        for event in ("desktop:register", "desktop:live2d_action", "desktop:chat_message"):
            assert event in events_bound, f"{event} should be registered"

    def test_register_routes_returns_route_handlers(
        self, mock_socketio, mock_session_manager
    ):
        """register_routes returns the RouteHandlers instance."""
        result = register_routes(mock_socketio, mock_session_manager)

        assert result.sio is mock_socketio
        assert result.session_manager is mock_session_manager
