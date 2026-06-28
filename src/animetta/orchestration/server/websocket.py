"""WebSocket server - Socket.IO server initialization and configuration"""

import datetime
from pathlib import Path
from typing import Any

import socketio
from loguru import logger
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route

from animetta.core.model_loading_manager import ModelLoadingManager
from animetta.core.service_pool import ServicePool
from animetta.tracing.bootstrap import init_tracing

from .desktop import DesktopClientManager
from .lifecycle import LifecycleManager
from .live2d import Live2DManager
from .routes import RouteHandlers, register_routes
from .session import SessionManager
from .stats_api import get_stats_routes, set_model_manager


class WebSocketServer:
    """WebSocket server"""

    def __init__(self, config=None):
        """Initialize WebSocket server"""
        self.config = config

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

        # Frontend static files (production build)
        frontend_dist = Path(__file__).parent.parent.parent.parent.parent / "frontend" / "dist"
        frontend_routes = []
        if frontend_dist.is_dir():
            from starlette.staticfiles import StaticFiles
            frontend_routes = [Mount("/app", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")]
            logger.info(f"[Socket.IO] Frontend static files mounted at /app from {frontend_dist}")

        self.asgi_app = Starlette(
            routes=stats_routes + metrics_route + singing_routes + frontend_routes + [Mount("/", app=sio_app)],
        )
        self.model_manager = ModelLoadingManager()
        set_model_manager(self.model_manager)
        self.session_manager = SessionManager(model_manager=self.model_manager)
        self.desktop_manager = DesktopClientManager()
        self.live2d_manager = Live2DManager()
        self.lifecycle = LifecycleManager()
        self.route_handlers: RouteHandlers | None = None

        logger.info("[Socket.IO] Server created with async_mode='asgi'")
        logger.info("[Socket.IO] CORS enabled: origins=*")

    def set_config(self, config) -> None:
        """Set application config"""
        self.config = config
        if self.route_handlers:
            self.route_handlers.set_global_config(config)

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
        """Load Bilibili configuration from config.yaml (top-level 'bilibili' key)."""
        try:
            from pathlib import Path

            import yaml
            config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "config.yaml"
            if config_path.exists():
                with open(config_path, encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                return data.get("bilibili")
        except Exception as e:
            logger.warning(f"[Bilibili] Failed to load config: {e}")
        return None

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

    async def _cleanup_all_resources(self) -> None:
        """Clean up all resources"""
        logger.info("Starting to clean up all resources...")

        # Stop Bilibili danmaku service
        if self.route_handlers:
            self.route_handlers.stop_bilibili()

        await self.session_manager.cleanup_all()
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
