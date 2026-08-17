"""WebSocket server - Socket.IO server initialization and configuration"""

import asyncio
import datetime
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import socketio
from loguru import logger
from prometheus_client import CollectorRegistry, generate_latest
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route

from animetta.config.manifest import EffectiveConfig
from animetta.config.observability import ObservabilityConfig
from animetta.config.runtime_reload import (
    RuntimeConfigApplyResult,
    RuntimeConfigReloader,
    apply_runtime_config_to_contexts,
    build_runtime_system_prompt,
)
from animetta.config.singing import load_singing_config
from animetta.config.user import UserSettings
from animetta.core.component_readiness import ComponentReadinessCache
from animetta.core.model_loading_manager import ModelLoadingManager
from animetta.core.readiness import frontend_asset_readiness, unwrap_tracing_proxy
from animetta.core.redis_checkpoint import RedisCheckpointRuntime
from animetta.core.service_pool import ServicePool
from animetta.core.shared_memory_runtime import SharedMemoryRuntime
from animetta.inspection.runtime import InspectionRuntime
from animetta.observability.domain import ObservationHealth
from animetta.observability.ledger import SQLiteObservationLedger
from animetta.observability.mirrors import OTelMirror, PrometheusMirror
from animetta.observability.ports import (
    NoOpObservationQuery,
    NoOpObservationRecorder,
    NoOpObservationReportStore,
    ObservationQuery,
    ObservationRecorder,
    ObservationReportStore,
)
from animetta.orchestration.graph.translation_state import translation_state
from animetta.orchestration.socket_events import EVENTS
from animetta.services.command_inbox import CommandInbox
from animetta.services.program_script import (
    ProgramReplayCoordinator,
    ProgramScriptRepository,
    ProgramScriptRunner,
)
from animetta.services.program_script.runtime import build_script_guidance
from animetta.utils.env_helper import get_data_dir

from .desktop import DesktopClientManager
from .lifecycle import LifecycleManager
from .live2d import Live2DManager
from .program_script_api import get_program_script_routes
from .routes import RouteHandlers, register_routes
from .security import AuthenticationMiddleware, SecurityRuntime, get_auth_routes
from .session import SessionManager
from .stats_api import (
    get_stats_routes,
    set_auth_session_readiness,
    set_auth_user_readiness,
    set_checkpoint_readiness,
    set_component_readiness_cache,
    set_model_manager,
    set_runtime_readiness_context,
)

SINGING_SOCKET_MAX_BUFFER_BYTES = 96 * 1024 * 1024


class WebSocketServer:
    """WebSocket server"""

    def __init__(
        self,
        config: EffectiveConfig | None = None,
        *,
        redis_url: str | None = None,
    ) -> None:
        """Initialize WebSocket server"""
        self.config = config
        translation_state.apply_runtime_config(config)
        self.runtime_reloader = RuntimeConfigReloader(config) if config is not None else None
        self._cleanup_lock = asyncio.Lock()
        self._observation_start_lock = asyncio.Lock()
        self._cleaned = False
        self.metrics_registry = CollectorRegistry()
        self.observation_mirrors: list[PrometheusMirror | OTelMirror] = []
        self.observation_ledger: SQLiteObservationLedger | None = None
        self.observation_recorder: ObservationRecorder
        self.observation_query: ObservationQuery
        self.observation_report_store: ObservationReportStore
        self._configure_observation_dependencies(config)
        self.security = SecurityRuntime.from_effective_config(
            config,
            observation_recorder=self.observation_recorder,
            redis_url=redis_url,
        )
        self.checkpoint_runtime = RedisCheckpointRuntime(redis_url)

        self.sio = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins=list(self.security.config.allowed_origins),
            cors_credentials=True,
            logger=False,
            engineio_logger=False,
            ping_timeout=120,
            ping_interval=30,
            # A 64 MiB decoded song expands to about 86 MiB as base64 JSON.
            max_http_buffer_size=SINGING_SOCKET_MAX_BUFFER_BYTES,
        )

        # Socket.IO ASGI + Stats API routes
        sio_app = socketio.ASGIApp(self.sio)
        stats_routes = get_stats_routes()

        # Prometheus /metrics endpoint (optional — graceful fallback if package not installed)
        metrics_route: list = []

        async def metrics_endpoint(request: Request) -> Response:
            del request
            return Response(
                generate_latest(self.metrics_registry),
                media_type="text/plain; charset=utf-8",
            )

        metrics_route = [Route("/metrics", metrics_endpoint)]

        # Singing media file serving (audio + subtitles)
        import mimetypes

        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
        self.command_inbox = CommandInbox(get_data_dir() / "command_inbox.db")
        self.memory_runtime = SharedMemoryRuntime(
            command_inbox=self.command_inbox,
            observation_recorder=self.observation_recorder,
        )
        self.program_repository = ProgramScriptRepository(
            get_data_dir() / "program_scripts",
            builtin_dir=project_root / "config" / "program_scripts",
        )
        self.program_runner = ProgramScriptRunner(
            self.program_repository,
            memory_runtime=self.memory_runtime,
            checkpoint_delete=self.checkpoint_runtime.delete_thread,
        )
        self.program_replay = ProgramReplayCoordinator(
            checkpoint_delete=self.checkpoint_runtime.delete_thread,
        )
        program_routes = get_program_script_routes(
            self.program_repository,
            self.program_runner,
            self.program_replay,
            command_inbox=self.command_inbox,
        )

        async def serve_singing_audio(request: Request) -> Response:
            filename = request.path_params.get("filename", "")
            filepath = project_root / "data" / "singing" / "outputs" / filename
            if not filepath.is_file():
                return Response("Not found", status_code=404)
            mime, _ = mimetypes.guess_type(filename)
            return FileResponse(str(filepath), media_type=mime or "audio/wav")

        async def serve_singing_subtitle(request: Request) -> Response:
            filename = request.path_params.get("filename", "")
            filepath = project_root / "data" / "singing" / "outputs" / filename
            if not filepath.is_file():
                return Response("Not found", status_code=404)
            return FileResponse(
                str(filepath),
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        async def serve_singing_recent(request: Request) -> JSONResponse:
            output_dir = project_root / "data" / "singing" / "outputs"
            if not output_dir.is_dir():
                return JSONResponse([])
            files = sorted(
                output_dir.glob("*_final.wav"), key=lambda f: f.stat().st_mtime, reverse=True
            )[:5]
            result = []
            for f in files:
                session_id = f.stem.replace("_final", "")
                subtitle = f.with_name(f"{session_id}_lyrics.ass")
                vocals = f.with_name(f"{session_id}_vocals.wav")
                tts = f.with_name(f"{session_id}_tts_final.wav")
                original = f.with_name(f"{session_id}_original.wav")
                result.append(
                    {
                        "session_id": session_id,
                        "audio_url": f"/api/singing/audio/{f.name}",
                        "vocals_url": f"/api/singing/audio/{vocals.name}"
                        if vocals.is_file()
                        else "",
                        "original_url": f"/api/singing/audio/{original.name}"
                        if original.is_file()
                        else "",
                        "subtitle_url": f"/api/singing/subtitle/{subtitle.name}"
                        if subtitle.is_file()
                        else "",
                        "tts_audio_url": f"/api/singing/audio/{tts.name}" if tts.is_file() else "",
                        "created_at": datetime.datetime.fromtimestamp(
                            f.stat().st_mtime
                        ).isoformat(),
                        "duration_sec": 0.0,
                    }
                )
            return JSONResponse(result)

        async def serve_singing_playlist(request: Request) -> JSONResponse:
            del request
            try:
                playlist = load_singing_config().playlist
            except (OSError, ValueError) as error:
                logger.error(f"Failed to load singing playlist: {error}")
                return JSONResponse({"error": "Singing playlist unavailable"}, status_code=500)
            return JSONResponse([entry.model_dump() for entry in playlist])

        singing_routes = [
            Route("/api/singing/audio/{filename:str}", serve_singing_audio),
            Route("/api/singing/subtitle/{filename:str}", serve_singing_subtitle),
            Route("/api/singing/playlist", serve_singing_playlist),
            Route("/api/singing/recent", serve_singing_recent),
        ]

        async def reload_config_endpoint(request: Request) -> JSONResponse:
            if self.runtime_reloader is None:
                if self.config is None:
                    return JSONResponse(
                        {
                            "ok": False,
                            "version": 1,
                            "persona": "",
                            "refreshed": [],
                            "error": "No active config to reload",
                        },
                        status_code=400,
                    )
                self.runtime_reloader = RuntimeConfigReloader(self.config)

            result = self.runtime_reloader.reload()
            if result.ok:
                apply_result = await self._apply_reloaded_config(
                    self.runtime_reloader.config,
                    result.version,
                )
                result.applied = apply_result.to_dict()
            return JSONResponse(result.to_dict(), status_code=200 if result.ok else 400)

        config_routes = [
            Route("/api/config/reload", reload_config_endpoint, methods=["POST"]),
        ]

        # Frontend static files (production build)
        frontend_dist = Path(__file__).parent.parent.parent.parent.parent / "frontend" / "dist"
        self.frontend_readiness = frontend_asset_readiness(frontend_dist)
        frontend_routes = []
        if frontend_dist.is_dir():
            from starlette.staticfiles import StaticFiles

            frontend_routes = [
                Mount("/app", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
            ]
            logger.info(f"[Socket.IO] Frontend static files mounted at /app from {frontend_dist}")

        @asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            auth_session_health, auth_user_health = await self.security.start()
            set_auth_session_readiness(auth_session_health.public_dict())
            set_auth_user_readiness(auth_user_health.public_dict())
            checkpoint_health = await self.checkpoint_runtime.start()
            set_checkpoint_readiness(checkpoint_health.public_dict())
            await self._start_observability()
            recovered = await self.command_inbox.start()
            if recovered:
                logger.warning("[CommandInbox] Interrupted {} stale command(s)", recovered)
            if checkpoint_health.available:
                try:
                    reconciled = await self.command_inbox.reconcile_waiting_approvals(
                        self.checkpoint_runtime.has_thread
                    )
                    if reconciled:
                        logger.warning(
                            "[CommandInbox] Failed {} approval(s) without checkpoints",
                            reconciled,
                        )
                except Exception as exc:
                    logger.warning(
                        "[CommandInbox] Approval reconciliation deferred: error_type={}",
                        type(exc).__name__,
                    )
            self.supervise_background(
                self._command_inbox_cleanup_loop(),
                name="command_inbox_cleanup",
            )
            self.supervise_background(
                self._approval_timeout_loop(),
                name="approval_timeout",
            )
            self.supervise_background(
                self._checkpoint_health_loop(),
                name="checkpoint_health",
            )
            self.supervise_background(
                self._auth_session_health_loop(),
                name="auth_session_health",
            )
            self.supervise_background(
                self._auth_user_health_loop(),
                name="auth_user_health",
            )
            await self.component_readiness_cache.start()
            if self.route_handlers:
                await self.route_handlers.start_runtime()
            try:
                yield
            finally:
                await self._cleanup_all_resources()

        self.asgi_app = Starlette(
            routes=get_auth_routes(self.security)
            + stats_routes
            + metrics_route
            + singing_routes
            + config_routes
            + program_routes
            + frontend_routes
            + [Mount("/", app=sio_app)],
            lifespan=lifespan,
        )
        self.asgi_app.add_middleware(AuthenticationMiddleware, security=self.security)
        self.asgi_app.add_middleware(
            CORSMiddleware,
            allow_origins=list(self.security.config.allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )
        self.asgi_app.state.observation_query = self.observation_query
        self.asgi_app.state.program_repository = self.program_repository
        self.asgi_app.state.program_runner = self.program_runner
        self.asgi_app.state.program_replay = self.program_replay
        self.asgi_app.state.command_inbox = self.command_inbox
        self.model_manager = ModelLoadingManager()
        set_model_manager(self.model_manager)
        ServicePool.configure_runtime(self.config, self.model_manager)
        set_runtime_readiness_context(self.config, self.frontend_readiness)
        self.component_readiness_cache = ComponentReadinessCache(self.inspection_runtime())
        set_component_readiness_cache(self.component_readiness_cache)
        self._unsubscribe_memory_revision = self.memory_runtime.subscribe_revision(
            lambda payload: self.supervise_background(
                self.sio.emit(EVENTS["memory"]["changed"]["name"], payload),
                name="memory_changed_emit",
            )
        )
        self.session_manager = SessionManager(
            model_manager=self.model_manager,
            memory_runtime=self.memory_runtime,
            observation_recorder=self.observation_recorder,
            checkpoint_runtime=self.checkpoint_runtime,
        )
        self.desktop_manager = DesktopClientManager()
        self.live2d_manager = Live2DManager()
        self.lifecycle = LifecycleManager()
        self.route_handlers: RouteHandlers | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

        logger.info("[Socket.IO] Server created with async_mode='asgi'")
        logger.info(
            "[Socket.IO] CORS enabled for {} exact origin(s)",
            len(self.security.config.allowed_origins),
        )

    def _configure_observation_dependencies(
        self,
        config: EffectiveConfig | None,
    ) -> None:
        observation = getattr(config, "observability", None)
        if not isinstance(observation, ObservabilityConfig) or not observation.enabled:
            self.observation_recorder = NoOpObservationRecorder()
            self.observation_query = NoOpObservationQuery()
            self.observation_report_store = NoOpObservationReportStore()
            self.cached_observation_health = ObservationHealth(
                enabled=False,
                ready=False,
                degraded=True,
            )
            return

        if observation.prometheus.enabled:
            self.observation_mirrors.append(PrometheusMirror(registry=self.metrics_registry))
        if observation.otlp.enabled:
            endpoint = observation.otlp.endpoint or "http://localhost:4317"
            try:
                self.observation_mirrors.append(
                    OTelMirror.from_endpoint(
                        endpoint,
                        max_export_batch_size=observation.otlp.max_export_batch_size,
                        schedule_delay_millis=observation.otlp.schedule_delay_millis,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "[Observability] OTLP mirror unavailable: error_type={}",
                    type(exc).__name__,
                )
                self.observation_mirrors.append(OTelMirror.unavailable(exc))

        ledger = SQLiteObservationLedger(
            observation.database_path,
            queue_capacity=observation.queue_capacity,
            busy_timeout_ms=observation.busy_timeout_ms,
            drain_timeout=observation.drain_timeout_seconds,
            mirrors=self.observation_mirrors,
        )
        self.observation_ledger = ledger
        self.observation_recorder = ledger
        self.observation_query = ledger
        self.observation_report_store = ledger
        self.cached_observation_health = ObservationHealth(
            enabled=True,
            ready=False,
            degraded=False,
        )

    async def _start_observability(self) -> None:
        async with self._observation_start_lock:
            if self.observation_ledger is None:
                self.cached_observation_health = await self.observation_recorder.health()
                return
            await self.observation_ledger.start()
            self.cached_observation_health = await self.observation_ledger.health()

    async def observation_health(self) -> ObservationHealth:
        self.cached_observation_health = await self.observation_recorder.health()
        return self.cached_observation_health

    def inspection_runtime(self) -> InspectionRuntime:
        """Return explicit, content-free dependencies for background inspection."""
        return InspectionRuntime(
            observation_query=self.observation_query,
            report_store=self.observation_report_store,
            memory_runtime=self.memory_runtime,
            readiness_snapshot=lambda: ServicePool.get_readiness_snapshot(
                config=self.config,
                model_manager=self.model_manager,
                frontend=self.frontend_readiness,
            ),
            metrics_snapshot=lambda: generate_latest(self.metrics_registry).decode(),
            observation_write_probe=self._probe_observation_pipeline,
            remote_tts_probe=(
                self._probe_remote_tts_dependency if self._requires_remote_tts() else None
            ),
        )

    def _requires_remote_tts(self) -> bool:
        providers = getattr(self.config, "providers", None)
        configured = providers.get("tts") if hasattr(providers, "get") else None
        return getattr(configured, "type", None) == "remote"

    async def _probe_remote_tts_dependency(self) -> dict[str, Any]:
        """Probe the selected remote worker from the background readiness owner."""
        target = unwrap_tracing_proxy(ServicePool.get_context().get("tts_engine"))
        check_readiness = getattr(target, "check_readiness", None)
        if not callable(check_readiness):
            raise RuntimeError("remote TTS readiness is unavailable")
        payload = await check_readiness()
        if not isinstance(payload, dict):
            raise RuntimeError("remote TTS readiness contract is invalid")
        return payload

    async def _probe_observation_pipeline(self) -> None:
        """Prove the local ledger is writable and the metric registry is live."""
        if self.observation_ledger is None:
            raise RuntimeError("observation ledger is unavailable")
        await self.observation_ledger.probe_write()
        mirrors = [
            mirror for mirror in self.observation_mirrors if isinstance(mirror, PrometheusMirror)
        ]
        if not mirrors:
            raise RuntimeError("prometheus mirror is unavailable")
        await asyncio.gather(*(mirror.probe() for mirror in mirrors))

    def set_config(self, config: EffectiveConfig) -> None:
        """Set application config"""
        self.config = config
        translation_state.apply_runtime_config(config)
        self.runtime_reloader = RuntimeConfigReloader(config)
        ServicePool.configure_runtime(config, self.model_manager)
        set_runtime_readiness_context(config, self.frontend_readiness)
        if self.route_handlers:
            self.route_handlers.set_global_config(config)

    async def _apply_reloaded_config(
        self,
        config: EffectiveConfig,
        version: int,
    ) -> RuntimeConfigApplyResult:
        """Apply a successfully reloaded config to active runtime holders."""
        self.config = config
        translation_state.apply_runtime_config(config)
        if self.runtime_reloader is not None:
            self.runtime_reloader._config = config
            self.runtime_reloader.version = version
        if self.route_handlers:
            self.route_handlers.set_global_config(config)
        ServicePool.configure_runtime(config, self.model_manager)
        set_runtime_readiness_context(config, self.frontend_readiness)

        llm_config = config.agent.llm_config if config.agent else None
        runtime_prompt = build_runtime_system_prompt(config)
        ServicePool.apply_llm_config(llm_config, system_prompt=runtime_prompt.system_prompt)
        apply_result = apply_runtime_config_to_contexts(
            config,
            version,
            self.session_manager.contexts.values(),
            runtime_prompt=runtime_prompt,
        )

        for warning in apply_result.prompt_warnings:
            logger.warning("[RuntimeConfigReload] {}", warning)

        return apply_result

    def set_user_settings(self, user_settings: UserSettings) -> None:
        """Set user settings"""
        if self.route_handlers:
            self.route_handlers.set_user_settings(user_settings)

    async def prewarm_services(self) -> None:
        """Pre-warm service imports and model loading at server startup.

        Initializes the global ServicePool so that the first user request
        reuses the already-loaded LLM/TTS/ASR engines instead of creating
        them from scratch.
        """
        await self._start_observability()
        if self.config is None:
            logger.info("[Prewarm] No config loaded yet, skipping")
            return

        await self.memory_runtime.initialize()
        await ServicePool.init(
            self.config,
            model_manager=self.model_manager,
            observation_recorder=self.observation_recorder,
        )
        await self.component_readiness_cache.refresh()

    def _load_bilibili_config(self) -> dict[str, Any] | None:
        """Return Bilibili configuration from the active app config."""
        bilibili_config = getattr(self.config, "bilibili", None)
        if bilibili_config is None:
            return None
        if isinstance(bilibili_config, dict):
            return bilibili_config
        if hasattr(bilibili_config, "model_dump"):
            return bilibili_config.model_dump()
        return {
            "enabled": getattr(bilibili_config, "enabled", False),
            "room_id": getattr(bilibili_config, "room_id", 0),
            "sessdata": getattr(bilibili_config, "sessdata", ""),
        }

    async def _dispatch_replay_event(self, event: Any) -> None:
        """Route one replay event through the production Bilibili reply boundary."""
        assert self.route_handlers is not None
        message = event.to_danmaku_message()
        context = dict(event.payload.get("program_context", {}))
        room_id = int(context.get("room_id", 1) or 1)
        if message is None:
            await self.route_handlers.bilibili._broadcast_live_event(
                event,
                room_id,
                0,
            )
            return
        context.setdefault("display_name", event.actor_id or "首播测试观众")
        context.setdefault("is_probe", True)
        reply = context.get("reply")
        if isinstance(reply, dict):
            context["scene_guidance"] = build_script_guidance(
                "弹幕重放",
                event.sequence + 1,
                reply,
            )
        await self.route_handlers.bilibili.process_program_danmaku(
            event.text,
            context,
            room_id=room_id,
        )
        if context.get("memory_mode") == "write":
            await self.memory_runtime.drain(timeout=15)

    def setup_routes(self) -> None:
        """Set up all routes"""
        bilibili_config = self._load_bilibili_config()

        self.route_handlers = register_routes(
            self.sio,
            self.session_manager,
            self.desktop_manager,
            self.live2d_manager,
            bilibili_config=bilibili_config,
            observation_recorder=self.observation_recorder,
            observation_query=self.observation_query,
            observation_report_store=self.observation_report_store,
            command_inbox=self.command_inbox,
            security=self.security,
        )

        async def dispatch_program(text: str, context: dict[str, Any]) -> dict[str, Any]:
            assert self.route_handlers is not None
            room_id = int(context.get("room_id", 1) or 1)
            return await self.route_handlers.bilibili.process_program_danmaku(
                text,
                context,
                room_id=room_id,
            )

        self.program_runner.set_dispatcher(dispatch_program)
        self.program_replay.set_dispatcher(self._dispatch_replay_event)
        self.program_runner.set_room_state_provider(
            lambda room_id: (
                {"state": "replay"}
                if self.program_replay.is_active(room_id)
                else self.route_handlers.bilibili.session.snapshot()
            )
        )
        self.program_replay.set_room_state_provider(
            lambda room_id: (
                {"state": "program"}
                if self.program_runner.is_active(room_id)
                else self.route_handlers.bilibili.session.snapshot()
            )
        )

        # Wire up model manager with Socket.IO for status events
        self.model_manager._socketio = self.sio

        logger.info("WebSocket routes registered")

    def setup_lifecycle(self) -> None:
        """Set up lifecycle management"""
        import asyncio

        shutdown_event = asyncio.Event()
        self.lifecycle.setup_signal_handlers(shutdown_event)
        self.lifecycle.register_cleanup_callback(self._cleanup_all_resources)
        logger.info("Lifecycle manager set up")

    def supervise_background(
        self,
        work: Coroutine[Any, Any, Any] | Callable[[], Coroutine[Any, Any, Any]],
        *,
        name: str,
    ) -> asyncio.Task[Any]:
        """Start, retain, and drain one background task safely."""
        coroutine = work() if callable(work) else work
        task = asyncio.ensure_future(coroutine)
        self._background_tasks.add(task)

        def on_done(completed: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(completed)
            if completed.cancelled():
                return
            try:
                error = completed.exception()
            except asyncio.CancelledError:
                return
            if error is not None:
                logger.warning(
                    "[BackgroundTask] {} failed: error_type={}",
                    name,
                    type(error).__name__,
                )

        task.add_done_callback(on_done)
        return task

    async def _command_inbox_cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(6 * 60 * 60)
            removed = await self.command_inbox.cleanup_expired()
            if removed:
                logger.info("[CommandInbox] Removed {} expired task(s)", removed)

    async def _approval_timeout_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            if self.route_handlers is not None:
                await self.route_handlers.expire_tool_approvals()

    async def _checkpoint_health_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            health = await self.checkpoint_runtime.check_health()
            set_checkpoint_readiness(health.public_dict())

    async def _auth_session_health_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            health = await self.security.check_session_health()
            set_auth_session_readiness(health.public_dict())

    async def _auth_user_health_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            health = await self.security.check_user_health()
            set_auth_user_readiness(health.public_dict())

    async def _stop_background_tasks(self) -> None:
        tasks = tuple(self._background_tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()

    async def _cleanup_all_resources(self) -> None:
        """Clean up all resources"""
        async with self._cleanup_lock:
            if self._cleaned:
                return
            self._cleaned = True
            await self._cleanup_resources_once()

    async def _cleanup_resources_once(self) -> None:
        logger.info("Starting to clean up all resources...")

        await self._stop_background_tasks()
        await self.program_replay.shutdown()
        await self.program_runner.shutdown()
        await self.component_readiness_cache.stop()

        if self.route_handlers:
            try:
                await self.route_handlers.stop_runtime()
            except Exception as exc:
                logger.warning(
                    "Bilibili cleanup failed: error_type={}",
                    type(exc).__name__,
                )

        try:
            await self.session_manager.cleanup_all()
        except Exception as exc:
            logger.warning(
                "Session cleanup failed: error_type={}",
                type(exc).__name__,
            )

        await self.memory_runtime.shutdown()
        await self.command_inbox.close()
        await self.security.close()
        set_auth_session_readiness(self.security.session_health.public_dict())
        set_auth_user_readiness(self.security.user_health.public_dict())
        await self.checkpoint_runtime.close()
        set_checkpoint_readiness(self.checkpoint_runtime.health.public_dict())
        await ServicePool.shutdown()
        if self.observation_ledger is not None:
            await self.observation_ledger.close()
            self.cached_observation_health = await self.observation_ledger.health()
        set_component_readiness_cache(None)
        logger.info("All resources cleaned up")

    def get_app(self) -> Starlette:
        """Get the ASGI app"""
        return self.asgi_app

    async def start(self) -> None:
        """Start the server"""
        await self._start_observability()
        self.setup_routes()
        self.setup_lifecycle()
        logger.info("WebSocket server started")

    async def stop(self) -> None:
        """Stop the server"""
        await self._cleanup_all_resources()
        logger.info("WebSocket server stopped")


def create_server(
    config: EffectiveConfig | None = None,
    *,
    redis_url: str | None = None,
) -> WebSocketServer:
    """Create a WebSocket server instance"""
    server = WebSocketServer(config, redis_url=redis_url)
    server.setup_routes()
    server.setup_lifecycle()
    # Pass config to route handlers
    if config:
        server.set_config(config)
    return server
