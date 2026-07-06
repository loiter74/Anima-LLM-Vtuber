from __future__ import annotations

"""Tests for WebSocket route handlers — event dispatch and registration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

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

    def test_set_user_settings(self, mock_socketio, mock_session_manager):
        """set_user_settings stores settings reference."""
        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        settings = MagicMock()
        handlers.set_user_settings(settings)
        assert handlers.user_settings is settings

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

        mock_socketio.emit.assert_any_call("system:error", {
            "type": "error",
            "message": "test error",
        }, to="sid1")

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
        # get_interrupt_handler is used as bare name in chat_handlers without import
        monkeypatch.setattr(
            "animetta.orchestration.server.handlers.chat_handlers.get_interrupt_handler",
            mock_interrupt_handler,
            raising=False,
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)

        await handlers.on_interrupt_signal("sid1", {"text": "stop please"})

        mock_interrupt.set_interrupt.assert_called_once_with("sid1")
        mock_socketio.emit.assert_any_call("chat:stop_audio", {}, to="sid1")
        mock_socketio.emit.assert_any_call("chat:control", {
            "type": "control",
            "text": "interrupted",
        }, to="sid1")

    @pytest.mark.asyncio
    async def test_on_memory_organize_uses_public_metabolism_api(
        self, mock_socketio, mock_session_manager
    ):
        """memory:organize should not reach into MemorySystem private methods."""

        class PublicMemorySystem:
            def __init__(self) -> None:
                self.tick_called = False

            async def run_metabolism_tick(self) -> None:
                self.tick_called = True

        memory = PublicMemorySystem()
        mock_session_manager.get_or_create_context = AsyncMock(
            return_value=SimpleNamespace(memory_system=memory)
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()

        await handlers.on_memory_organize("sid1", {})

        assert memory.tick_called
        mock_socketio.emit.assert_any_call(
            "memory:organize_result",
            {"status": "ok", "message": "Memory organized"},
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
            async def list_wiki_pages(self, limit: int = 50) -> list[dict]:
                assert limit == 50
                return pages

        mock_session_manager.get_or_create_context = AsyncMock(
            return_value=SimpleNamespace(memory_system=PublicMemorySystem())
        )

        handlers = RouteHandlers(mock_socketio, mock_session_manager)
        handlers.global_config = MagicMock()

        assert await handlers.on_get_wiki_pages("sid1", {}) == {"pages": pages}


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
