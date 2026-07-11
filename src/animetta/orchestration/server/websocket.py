"""WebSocket server - Socket.IO server initialization and configuration"""

import asyncio
import datetime
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import socketio
from loguru import logger
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route

from animetta.config.runtime_reload import (
    RuntimeConfigReloader,
    apply_runtime_config_to_contexts,
    build_runtime_system_prompt,
)
from animetta.core.model_loading_manager import ModelLoadingManager
from animetta.core.readiness import frontend_asset_readiness
from animetta.core.service_pool import ServicePool
from animetta.tracing.bootstrap import init_tracing

from .desktop import DesktopClientManager
from .lifecycle import LifecycleManager
from .live2d import Live2DManager
from .routes import RouteHandlers, register_routes
from .session import SessionManager
from .stats_api import (
    get_stats_routes,
    set_model_manager,
    set_runtime_readiness_context,
)


class WebSocketServer:
    """WebSocket server"""

    def __init__(self, config=None):
        """Initialize WebSocket server"""
        self.config = config
        self.runtime_reloader = RuntimeConfigReloader(config) if config is not None else None

        self.sio = socketio.AsyncServer(
            async_mode='asgi',
            cors_allowed_origins='*',
            cors_credentials=True,
            logger=False,
            engineio_logger=False,
            ping_timeout=120,
            ping_interval=30,
            max_http_buffer_size=10_000_000,  # 10MB for singing file uploads
        )

        # Socket.IO ASGI + Stats API routes
        sio_app = socketio.ASGIApp(self.sio)
        stats_routes = get_stats_routes()

        # Prometheus /metrics endpoint (optional — graceful fallback if package not installed)
        metrics_route: list = []
        try:
            from prometheus_client import REGISTRY, generate_latest

            async def metrics_endpoint(request):
                return Response(generate_latest(REGISTRY), media_type="text/plain; charset=utf-8")

            metrics_route = [Route("/metrics", metrics_endpoint)]
        except ImportError:
            logger.warning("[Metrics] prometheus-client not installed — /metrics disabled")

        # Singing media file serving (audio + subtitles)
        import mimetypes
        project_root = Path(__file__).resolve().parent.parent.parent.parent.parent

        async def serve_singing_audio(request):
            filename = request.path_params.get("filename", "")
            filepath = project_root / "data" / "singing" / "outputs" / filename
            if not filepath.is_file():
                return Response("Not found", status_code=404)
            mime, _ = mimetypes.guess_type(filename)
            return FileResponse(str(filepath), media_type=mime or "audio/wav")

        async def serve_singing_subtitle(request):
            filename = request.path_params.get("filename", "")
            filepath = project_root / "data" / "singing" / "outputs" / filename
            if not filepath.is_file():
                return Response("Not found", status_code=404)
            return FileResponse(
                str(filepath),
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        async def serve_singing_recent(request):
            output_dir = project_root / "data" / "singing" / "outputs"
            if not output_dir.is_dir():
                return JSONResponse([])
            files = sorted(output_dir.glob("*_final.wav"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]
            result = []
            for f in files:
                session_id = f.stem.replace("_final", "")
                subtitle = f.with_name(f"{session_id}_lyrics.ass")
                vocals = f.with_name(f"{session_id}_vocals.wav")
                tts = f.with_name(f"{session_id}_tts_final.wav")
                original = f.with_name(f"{session_id}_original.wav")
                result.append({
                    "session_id": session_id,
                    "audio_url": f"/api/singing/audio/{f.name}",
                    "vocals_url": f"/api/singing/audio/{vocals.name}" if vocals.is_file() else "",
                    "original_url": f"/api/singing/audio/{original.name}" if original.is_file() else "",
                    "subtitle_url": f"/api/singing/subtitle/{subtitle.name}" if subtitle.is_file() else "",
                    "tts_audio_url": f"/api/singing/audio/{tts.name}" if tts.is_file() else "",
                    "created_at": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "duration_sec": 0.0,
                })
            return JSONResponse(result)

        singing_routes = [
            Route("/api/singing/audio/{filename:str}", serve_singing_audio),
            Route("/api/singing/subtitle/{filename:str}", serve_singing_subtitle),
            Route("/api/singing/recent", serve_singing_recent),
        ]

        async def reload_config_endpoint(request):
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
            frontend_routes = [Mount("/app", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")]
            logger.info(f"[Socket.IO] Frontend static files mounted at /app from {frontend_dist}")

        self.asgi_app = Starlette(
            routes=stats_routes + metrics_route + singing_routes + config_routes + frontend_routes + [Mount("/", app=sio_app)],
        )
        self.model_manager = ModelLoadingManager()
        set_model_manager(self.model_manager)
        ServicePool.configure_runtime(self.config, self.model_manager)
        set_runtime_readiness_context(self.config, self.frontend_readiness)
        self.session_manager = SessionManager(model_manager=self.model_manager)
        self.desktop_manager = DesktopClientManager()
        self.live2d_manager = Live2DManager()
        self.lifecycle = LifecycleManager()
        self.route_handlers: RouteHandlers | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

        logger.info("[Socket.IO] Server created with async_mode='asgi'")
        logger.info("[Socket.IO] CORS enabled: origins=*")

    def set_config(self, config) -> None:
        """Set application config"""
        self.config = config
        self.runtime_reloader = RuntimeConfigReloader(config)
        ServicePool.configure_runtime(config, self.model_manager)
        set_runtime_readiness_context(config, self.frontend_readiness)
        if self.route_handlers:
            self.route_handlers.set_global_config(config)

    async def _apply_reloaded_config(self, config, version: int):
        """Apply a successfully reloaded config to active runtime holders."""
        self.config = config
        if self.runtime_reloader is not None:
            self.runtime_reloader._config = config
            self.runtime_reloader.version = version
        if self.route_handlers:
            self.route_handlers.set_global_config(config)

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

    def set_user_settings(self, user_settings) -> None:
        """Set user settings"""
        if self.route_handlers:
            self.route_handlers.set_user_settings(user_settings)

    def setup_tracing(self) -> None:
        """Initialize OpenTelemetry tracing pipeline."""
        init_tracing()

    async def prewarm_services(self) -> None:
        """Pre-warm service imports and model loading at server startup.

        Initializes the global ServicePool so that the first user request
        reuses the already-loaded LLM/TTS/ASR engines instead of creating
        them from scratch.
        """
        if self.config is None:
            logger.info("[Prewarm] No config loaded yet, skipping")
            return

        await ServicePool.init(self.config, model_manager=self.model_manager)

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

    def setup_routes(self) -> None:
        """Set up all routes"""
        bilibili_config = self._load_bilibili_config()

        self.route_handlers = register_routes(
            self.sio,
            self.session_manager,
            self.desktop_manager,
            self.live2d_manager,
            bilibili_config=bilibili_config,
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
        logger.info("Starting to clean up all resources...")

        await self._stop_background_tasks()

        if self.route_handlers:
            try:
                self.route_handlers.stop_bilibili()
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

        await ServicePool.shutdown()
        logger.info("All resources cleaned up")

    def get_app(self):
        """Get the ASGI app"""
        return self.asgi_app

    async def start(self) -> None:
        """Start the server"""
        self.setup_routes()
        self.setup_lifecycle()
        logger.info("WebSocket server started")

    async def stop(self) -> None:
        """Stop the server"""
        await self._cleanup_all_resources()
        logger.info("WebSocket server stopped")


def create_server(config=None) -> WebSocketServer:
    """Create a WebSocket server instance"""
    server = WebSocketServer(config)
    server.setup_tracing()
    server.setup_routes()
    server.setup_lifecycle()
    # Pass config to route handlers
    if config:
        server.set_config(config)
    return server
