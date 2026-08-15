from __future__ import annotations

"""Tests for WebSocketServer — server init, routes, lifecycle, and prewarm."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from animetta.config.manifest import load_effective_config
from animetta.orchestration.server.websocket import WebSocketServer, create_server
from animetta.services.bilibili import LivestreamEvent, LivestreamEventType


def _effective_config(*, observability: dict | None = None):
    with patch.dict(
        os.environ,
        {
            "ANIMETTA_PROFILE": "test",
            "ANIMETTA_HOST": "127.0.0.1",
            "ANIMETTA_PORT": "12394",
        },
        clear=True,
    ):
        config = load_effective_config("config/animetta.yaml", profile="test")
    if observability is None:
        return config
    application = config.application.model_copy(update={"observability": observability})
    return config.model_copy(update={"application": application})


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def websocket_server():
    """WebSocketServer with mocked internals."""
    with (
        patch("socketio.AsyncServer") as mock_sio_cls,
        patch("socketio.ASGIApp") as mock_asgi,
        patch("starlette.applications.Starlette") as mock_starlette,
        patch("animetta.orchestration.server.websocket.ModelLoadingManager") as mock_mlm,
    ):
        mock_sio_cls.return_value = MagicMock()
        mock_asgi.return_value = MagicMock()
        mock_starlette.return_value = MagicMock()
        mock_mlm.return_value = MagicMock()
        server = WebSocketServer(config=_effective_config())
        return server


# ── WebSocketServer — Init ─────────────────────────────────────────


class TestWebSocketServerInit:
    """Server construction and default attributes."""

    def test_init_creates_sio_and_asgi(self):
        """__init__ creates Socket.IO server and Starlette ASGI app."""
        with (
            patch("socketio.AsyncServer") as mock_sio_cls,
            patch("socketio.ASGIApp") as mock_asgi,
            patch("starlette.applications.Starlette") as mock_starlette,
            patch("animetta.orchestration.server.websocket.ModelLoadingManager") as mock_mlm,
        ):
            mock_sio_cls.return_value = MagicMock()
            mock_asgi.return_value = MagicMock()
            mock_starlette.return_value = MagicMock()
            mock_mlm.return_value = MagicMock()

            config = _effective_config()
            server = WebSocketServer(config=config)

            assert server.config is config
            assert server.sio is not None
            assert server.asgi_app is not None
            assert server.model_manager is not None
            assert server.memory_runtime is not None
            assert server.session_manager is not None
            assert server.session_manager.memory_runtime is server.memory_runtime
            assert server.desktop_manager is not None
            assert server.live2d_manager is not None
            assert server.lifecycle is not None
            assert server.route_handlers is None
            assert server._background_tasks == set()
            assert server.frontend_readiness["state"] in {"ready", "failed"}
            assert isinstance(server.frontend_readiness["ready"], bool)
            assert "path" not in server.frontend_readiness

            mock_sio_cls.assert_called_once_with(
                async_mode="asgi",
                cors_allowed_origins=list(config.security.allowed_origins),
                cors_credentials=True,
                logger=False,
                engineio_logger=False,
                ping_timeout=120,
                ping_interval=30,
                max_http_buffer_size=96 * 1024 * 1024,
            )

    def test_init_stores_config(self):
        """Config is stored when provided."""
        with (
            patch("socketio.AsyncServer") as mock_sio_cls,
            patch("socketio.ASGIApp") as mock_asgi,
            patch("starlette.applications.Starlette") as mock_starlette,
            patch("animetta.orchestration.server.websocket.ModelLoadingManager"),
        ):
            mock_sio_cls.return_value = MagicMock()
            mock_asgi.return_value = MagicMock()
            mock_starlette.return_value = MagicMock()

            cfg = _effective_config()
            server = WebSocketServer(config=cfg)
            assert server.config is cfg

    def test_get_app_returns_asgi_app(self, websocket_server):
        """get_app returns the Starlette ASGI app."""
        app = websocket_server.get_app()
        assert app is websocket_server.asgi_app


class TestReplayDispatchBoundary:
    @staticmethod
    def _event(
        *,
        event_type: LivestreamEventType = LivestreamEventType.DANMAKU,
        context: dict | None = None,
    ) -> LivestreamEvent:
        return LivestreamEvent(
            sequence=0,
            offset_ms=0,
            event_type=event_type,
            actor_id="结构回归观众",
            text="暗号是什么？",
            payload={"program_context": context or {}},
        )

    async def test_missing_probe_flag_defaults_to_true(self, websocket_server) -> None:
        bilibili = SimpleNamespace(
            process_program_danmaku=AsyncMock(return_value={}),
            _broadcast_live_event=AsyncMock(),
        )
        websocket_server.route_handlers = SimpleNamespace(bilibili=bilibili)

        await websocket_server._dispatch_replay_event(self._event())

        context = bilibili.process_program_danmaku.await_args.args[1]
        assert context["is_probe"] is True

    async def test_explicit_false_probe_flag_is_preserved(self, websocket_server) -> None:
        bilibili = SimpleNamespace(
            process_program_danmaku=AsyncMock(return_value={}),
            _broadcast_live_event=AsyncMock(),
        )
        websocket_server.route_handlers = SimpleNamespace(bilibili=bilibili)

        await websocket_server._dispatch_replay_event(self._event(context={"is_probe": False}))

        context = bilibili.process_program_danmaku.await_args.args[1]
        assert context["is_probe"] is False

    async def test_non_replyable_event_only_broadcasts(self, websocket_server) -> None:
        bilibili = SimpleNamespace(
            process_program_danmaku=AsyncMock(return_value={}),
            _broadcast_live_event=AsyncMock(),
        )
        websocket_server.route_handlers = SimpleNamespace(bilibili=bilibili)

        event = self._event(event_type=LivestreamEventType.ENTER)
        await websocket_server._dispatch_replay_event(event)

        bilibili._broadcast_live_event.assert_awaited_once_with(event, 1, 0)
        bilibili.process_program_danmaku.assert_not_awaited()

    @pytest.mark.parametrize("memory_mode", ["off", "probe", None])
    async def test_non_write_memory_mode_does_not_drain(
        self,
        websocket_server,
        memory_mode: str | None,
    ) -> None:
        bilibili = SimpleNamespace(
            process_program_danmaku=AsyncMock(return_value={}),
            _broadcast_live_event=AsyncMock(),
        )
        websocket_server.route_handlers = SimpleNamespace(bilibili=bilibili)
        drain = AsyncMock()
        websocket_server.memory_runtime = SimpleNamespace(drain=drain)
        context = {"memory_mode": memory_mode} if memory_mode is not None else {}

        await websocket_server._dispatch_replay_event(self._event(context=context))

        drain.assert_not_awaited()

    async def test_write_memory_mode_drains_after_dispatch(self, websocket_server) -> None:
        bilibili = SimpleNamespace(
            process_program_danmaku=AsyncMock(return_value={}),
            _broadcast_live_event=AsyncMock(),
        )
        websocket_server.route_handlers = SimpleNamespace(bilibili=bilibili)
        drain = AsyncMock()
        websocket_server.memory_runtime = SimpleNamespace(drain=drain)

        await websocket_server._dispatch_replay_event(self._event(context={"memory_mode": "write"}))

        drain.assert_awaited_once_with(timeout=15)


# ── WebSocketServer — Singing media routes ─────────────────────────


class TestSingingMediaRoutes:
    """Lightweight HTTP route probes for singing media endpoints."""

    @staticmethod
    def _server_with_real_routes(config=None):
        with (
            patch("animetta.orchestration.server.websocket.ModelLoadingManager") as mock_mlm,
            patch("animetta.orchestration.server.websocket.SessionManager") as mock_sessions,
            patch("animetta.orchestration.server.websocket.DesktopClientManager") as mock_desktop,
            patch("animetta.orchestration.server.websocket.Live2DManager") as mock_live2d,
            patch("animetta.orchestration.server.websocket.LifecycleManager") as mock_lifecycle,
        ):
            mock_mlm.return_value = MagicMock()
            mock_sessions.return_value = MagicMock()
            mock_desktop.return_value = MagicMock()
            mock_live2d.return_value = MagicMock()
            mock_lifecycle.return_value = MagicMock()
            return WebSocketServer(config=config)

    def test_metrics_endpoint_exposes_committed_record_projection(self, tmp_path):
        server = self._server_with_real_routes(
            _effective_config(
                observability={
                    "database_path": str(tmp_path / "observations.db"),
                    "otlp": {"enabled": False},
                }
            )
        )

        with TestClient(server.get_app()) as client:
            response = client.get("/metrics")

        assert response.status_code == 200
        assert "anima_active_sessions" in response.text

    def test_singing_recent_returns_empty_list_when_no_outputs(self):
        """GET /api/singing/recent returns [] instead of raising when output dir is absent."""
        server = self._server_with_real_routes()

        with TestClient(server.get_app()) as client:
            response = client.get("/api/singing/recent")

        assert response.status_code == 200
        assert response.json() == []

    def test_singing_subtitle_missing_file_returns_404(self):
        """GET /api/singing/subtitle/{filename} returns 404 for missing files."""
        server = self._server_with_real_routes()

        with TestClient(server.get_app()) as client:
            response = client.get("/api/singing/subtitle/missing.ass")

        assert response.status_code == 404

    def test_singing_audio_missing_file_returns_404(self):
        """GET /api/singing/audio/{filename} returns 404 for missing files."""
        server = self._server_with_real_routes()

        with TestClient(server.get_app()) as client:
            response = client.get("/api/singing/audio/missing.wav")

        assert response.status_code == 404


# ── WebSocketServer — set_config ────────────────────────────────────


class TestSetConfig:
    """set_config delegation."""

    def test_set_config_stores_config(self, websocket_server):
        """set_config stores config and forwards to route_handlers."""
        new_config = MagicMock()
        h = MagicMock()
        websocket_server.route_handlers = h

        websocket_server.set_config(new_config)

        assert websocket_server.config is new_config
        h.set_global_config.assert_called_once_with(new_config)

    def test_set_config_no_handlers(self, websocket_server):
        """set_config works when route_handlers is None."""
        cfg = MagicMock()
        websocket_server.set_config(cfg)
        assert websocket_server.config is cfg

    def test_set_config_applies_subtitle_translation_runtime_default(self, websocket_server):
        from animetta.orchestration.graph.translation_state import translation_state

        previous = translation_state.enabled
        cfg = MagicMock()
        cfg.system.enable_subtitle_translation = False
        try:
            websocket_server.set_config(cfg)
            assert translation_state.enabled is False
        finally:
            translation_state.enabled = previous


# ── WebSocketServer — setup_routes ─────────────────────────────────


class TestSetupRoutes:
    """Route registration."""

    def test_setup_routes_creates_handlers(self, websocket_server):
        """setup_routes creates route_handlers via register_routes."""
        with patch("animetta.orchestration.server.websocket.register_routes") as mock_reg:
            mock_reg.return_value = MagicMock()

            websocket_server.setup_routes()

            assert websocket_server.route_handlers is not None
            mock_reg.assert_called_once_with(
                websocket_server.sio,
                websocket_server.session_manager,
                websocket_server.desktop_manager,
                websocket_server.live2d_manager,
                bilibili_config=mock_reg.call_args[1]["bilibili_config"],
                observation_recorder=websocket_server.observation_recorder,
                observation_query=websocket_server.observation_query,
                observation_report_store=websocket_server.observation_report_store,
                command_inbox=websocket_server.command_inbox,
                security=websocket_server.security,
            )

    def test_setup_routes_wires_socketio_to_model_manager(self, websocket_server):
        """model_manager._socketio is wired after setup_routes."""
        with patch("animetta.orchestration.server.websocket.register_routes") as mock_reg:
            mock_reg.return_value = MagicMock()

            websocket_server.setup_routes()

            assert websocket_server.model_manager._socketio is websocket_server.sio

    def test_setup_routes_uses_app_config_bilibili(self, websocket_server):
        """Bilibili startup config should come from the effective config."""
        websocket_server.config = SimpleNamespace(
            bilibili=SimpleNamespace(
                enabled=True,
                room_id=12345,
                sessdata="sess",
            )
        )

        with patch("animetta.orchestration.server.websocket.register_routes") as mock_reg:
            mock_reg.return_value = MagicMock()

            websocket_server.setup_routes()

            assert mock_reg.call_args.kwargs["bilibili_config"] == {
                "enabled": True,
                "room_id": 12345,
                "sessdata": "sess",
            }


# ── WebSocketServer — setup_lifecycle ──────────────────────────────


class TestSetupLifecycle:
    """Signal handlers and cleanup callbacks."""

    def test_setup_lifecycle_registers_signal_handlers(self, websocket_server):
        """setup_lifecycle sets up signal handlers and cleanup callback."""
        websocket_server.setup_lifecycle()

        assert websocket_server.lifecycle._signal_handlers_set is True
        assert len(websocket_server.lifecycle._cleanup_callbacks) == 1

    def test_setup_lifecycle_cleanup_callback_is_cleanup_all(self, websocket_server):
        """The registered cleanup callback references _cleanup_all_resources."""
        websocket_server.setup_lifecycle()

        cb = websocket_server.lifecycle._cleanup_callbacks[0]
        # Bound method of websocket_server
        assert cb.__self__ is websocket_server
        assert cb.__func__.__name__ == "_cleanup_all_resources"


# ── WebSocketServer — prewarm_services ─────────────────────────────


class TestPrewarmServices:
    """Service prewarming."""

    @pytest.mark.asyncio
    async def test_prewarm_services_with_config(self, websocket_server):
        """prewarm_services initializes ServicePool when config is set."""
        websocket_server.memory_runtime.initialize = AsyncMock()
        with patch("animetta.orchestration.server.websocket.ServicePool") as mock_pool:
            mock_pool.init = AsyncMock()

            await websocket_server.prewarm_services()

            mock_pool.init.assert_called_once_with(
                websocket_server.config,
                model_manager=websocket_server.model_manager,
                observation_recorder=websocket_server.observation_recorder,
            )
            websocket_server.memory_runtime.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prewarm_services_no_config(self):
        """prewarm_services skips when config is None."""
        with (
            patch("socketio.AsyncServer") as mock_sio_cls,
            patch("socketio.ASGIApp") as mock_asgi,
            patch("starlette.applications.Starlette") as mock_starlette,
            patch("animetta.orchestration.server.websocket.ModelLoadingManager"),
        ):
            mock_sio_cls.return_value = MagicMock()
            mock_asgi.return_value = MagicMock()
            mock_starlette.return_value = MagicMock()

            server = WebSocketServer(config=None)

        with patch("animetta.orchestration.server.websocket.ServicePool") as mock_pool:
            await server.prewarm_services()
            mock_pool.init.assert_not_called()


# ── WebSocketServer — cleanup ──────────────────────────────────────


class TestCleanup:
    """Resource cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_all_resources_stops_bilibili_and_sessions(self, websocket_server):
        """_cleanup_all_resources stops bilibili and cleans up sessions."""
        route_handlers = MagicMock()
        route_handlers.stop_runtime = AsyncMock()
        websocket_server.route_handlers = route_handlers
        websocket_server.session_manager.cleanup_all = AsyncMock()
        websocket_server.memory_runtime.shutdown = AsyncMock()

        with patch(
            "animetta.orchestration.server.websocket.ServicePool.shutdown",
            new=AsyncMock(),
        ) as shutdown:
            await websocket_server._cleanup_all_resources()

        route_handlers.stop_runtime.assert_awaited_once()
        websocket_server.session_manager.cleanup_all.assert_called_once()
        shutdown.assert_awaited_once_with()
        websocket_server.memory_runtime.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_calls_cleanup(self, websocket_server):
        """stop() triggers _cleanup_all_resources."""
        websocket_server.session_manager.cleanup_all = AsyncMock()

        with patch(
            "animetta.orchestration.server.websocket.ServicePool.shutdown",
            new=AsyncMock(),
        ) as shutdown:
            await websocket_server.stop()

        websocket_server.session_manager.cleanup_all.assert_called_once()
        shutdown.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_cleanup_still_shuts_pool_when_session_cleanup_fails(
        self,
        websocket_server,
    ):
        websocket_server.session_manager.cleanup_all = AsyncMock(
            side_effect=RuntimeError("sensitive-session-error")
        )

        with (
            patch(
                "animetta.orchestration.server.websocket.ServicePool.shutdown",
                new=AsyncMock(),
            ) as shutdown,
            patch("animetta.orchestration.server.websocket.logger.warning") as warning,
        ):
            await websocket_server._cleanup_all_resources()

        shutdown.assert_awaited_once_with()
        rendered = repr(warning.call_args_list)
        assert "RuntimeError" in rendered
        assert "sensitive-session-error" not in rendered


class TestBackgroundTaskSupervisor:
    """Tracked startup tasks are drained and stopped deterministically."""

    @pytest.mark.asyncio
    async def test_background_failure_is_drained_with_type_only_log(
        self,
        websocket_server,
    ):
        async def fail() -> None:
            raise RuntimeError("sensitive-background-error")

        with patch("animetta.orchestration.server.websocket.logger.warning") as warning:
            task = websocket_server.supervise_background(
                fail(),
                name="service-prewarm",
            )
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)

        assert task not in websocket_server._background_tasks
        rendered = repr(warning.call_args_list)
        assert "RuntimeError" in rendered
        assert "sensitive-background-error" not in rendered

    @pytest.mark.asyncio
    async def test_stop_cancels_and_awaits_background_tasks(
        self,
        websocket_server,
    ):
        entered = asyncio.Event()
        cancelled = asyncio.Event()

        async def pending() -> None:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = websocket_server.supervise_background(
            pending(),
            name="service-prewarm",
        )
        await entered.wait()
        websocket_server.session_manager.cleanup_all = AsyncMock()

        with patch(
            "animetta.orchestration.server.websocket.ServicePool.shutdown",
            new=AsyncMock(),
        ) as shutdown:
            await websocket_server.stop()

        assert cancelled.is_set()
        assert task.cancelled()
        assert websocket_server._background_tasks == set()
        shutdown.assert_awaited_once_with()


# ── WebSocketServer — start ────────────────────────────────────────


class TestStart:
    """Server startup."""

    @pytest.mark.asyncio
    async def test_start_calls_setup_methods(self, websocket_server):
        """start() calls setup_routes and setup_lifecycle."""
        with (
            patch.object(websocket_server, "setup_routes") as mock_routes,
            patch.object(websocket_server, "setup_lifecycle") as mock_lifecycle,
        ):
            await websocket_server.start()

            mock_routes.assert_called_once()
            mock_lifecycle.assert_called_once()


# ── create_server ──────────────────────────────────────────────────


class TestCreateServer:
    """create_server factory function."""

    def test_create_server_creates_and_configures(self):
        """create_server builds server, routes, and lifecycle."""
        with (
            patch("socketio.AsyncServer") as mock_sio_cls,
            patch("socketio.ASGIApp") as mock_asgi,
            patch("starlette.applications.Starlette") as mock_starlette,
            patch("animetta.orchestration.server.websocket.ModelLoadingManager"),
        ):
            mock_sio_cls.return_value = MagicMock()
            mock_asgi.return_value = MagicMock()
            mock_starlette.return_value = MagicMock()

            cfg = _effective_config()

            with (
                patch.object(WebSocketServer, "setup_routes") as mock_routes,
                patch.object(WebSocketServer, "setup_lifecycle") as mock_lifecycle,
            ):
                server = create_server(config=cfg)

                assert isinstance(server, WebSocketServer)
                mock_routes.assert_called_once()
                mock_lifecycle.assert_called_once()
