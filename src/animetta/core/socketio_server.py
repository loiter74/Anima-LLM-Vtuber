"""
Socket.IO server entry point
Uses server/ module components to build the server
"""

import argparse
import sys
from pathlib import Path

current_dir = Path(__file__).resolve().parent
_PROJECT_ROOT = current_dir.parents[2]

# Fix module import path: add src directory to Python path
src_dir = _PROJECT_ROOT / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from loguru import logger

from animetta.config.app import AppConfig
from animetta.config.user import UserSettings
from animetta.core.redis_checkpoint import AsyncRedisSaver
from animetta.inspection.scheduler import InspectionScheduler
from animetta.orchestration.graph.builder import set_external_checkpointer
from animetta.orchestration.server.websocket import WebSocketServer, create_server
from animetta.utils.logger_manager import logger_manager

# Load environment variables from .env file (must be before other imports)
try:
    from dotenv import load_dotenv
    env_path = _PROJECT_ROOT / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=True)
        logger.info(f"[OK] Environment variables loaded from: {env_path}")
    else:
        logger.warning(f".env file not found: {env_path}, using system environment variables")
except ImportError:
    logger.info("python-dotenv not installed, using system environment variables")

import asyncio
import threading

import uvicorn


def parse_server_args() -> argparse.Namespace:
    """Parse server CLI arguments."""
    parser = argparse.ArgumentParser(description="Animetta Socket.IO Server")
    parser.add_argument(
        "--redis-url",
        type=str,
        default=None,
        help="Redis URL for session checkpoint sharing (e.g. redis://localhost:6379)",
    )
    return parser.parse_args()


_server_args = parse_server_args()


# Global configuration
global_config: AppConfig = None

# User settings
user_settings = UserSettings(_PROJECT_ROOT)

# Apply user-configured log level
initial_log_level = user_settings.get_log_level()
logger_manager.set_level(initial_log_level)
logger.info(f"Applying user log level configuration: {initial_log_level}")


def init_config(config_path: str = None) -> None:
    """
    Initialize global configuration

    Args:
        config_path: YAML configuration file path (optional)
    """
    global global_config

    global_config = AppConfig.from_yaml(config_path) if config_path else AppConfig.load()

    logger.info(f"Configuration loaded: {global_config.system.host}:{global_config.system.port}")


def run_server():
    """Run the server using uvicorn (ASGI mode)"""
    import atexit

    # Initialize configuration
    init_config()

    # Create server
    _server = create_server(global_config)
    _server.set_user_settings(user_settings)

    # Register cleanup function on exit
    def cleanup_on_exit():
        logger.info("Server shutting down...")
        try:
            asyncio.run(_server.stop())
        except NameError:
            pass  # server not initialized
        except Exception as e:
            logger.error(f"Error cleaning up resources: {e}")
        logger.info("Server shut down")

    atexit.register(cleanup_on_exit)

    logger.info("=" * 50)
    logger.info("Starting Socket.IO server...")
    logger.info(f"Host: {global_config.system.host}")
    logger.info(f"Port: {global_config.system.port}")
    logger.info("Socket.IO async_mode: asgi (uvicorn)")
    logger.info("=" * 50)
    logger.info(f"Visit http://{global_config.system.host}:{global_config.system.port} to test")
    logger.info(f"WebSocket URL: ws://{global_config.system.host}:{global_config.system.port}/socket.io/")

    # Run uvicorn server - use factory function to ensure proper initialization
    uvicorn.run(
        "animetta.core.socketio_server:get_asgi_app",
        host=global_config.system.host,
        port=global_config.system.port,
        log_level="info",
        factory=True
    )


# Create ASGI application (for uvicorn import)
_server: WebSocketServer = None
asgi_app = None

# ── Duplicate-init guards ─────────────────────────────────────────────
# threading.Event survives module re-import (uvicorn reload/fork) where
# `asgi_app is None` does not. Track background tasks so stale ones can
# be cancelled if re-init is somehow triggered.
_INIT_DONE = threading.Event()
_INIT_TASKS: list[asyncio.Task] = []


def get_asgi_app():
    """Get ASGI application (lazy initialization)"""
    global _server, asgi_app, global_config, user_settings

    if _INIT_DONE.is_set():
        return asgi_app

    if asgi_app is None:
        # Cancel any stale tasks from a prior init attempt (belt-and-suspenders)
        for t in _INIT_TASKS[:]:
            if not t.done():
                t.cancel()
        _INIT_TASKS.clear()

        # Ensure config is loaded (needed when run as uvicorn subprocess)
        global global_config
        if global_config is None:
            init_config()

        # ── File logging for Loki ingestion ─────────────────────
        logs_dir = _PROJECT_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(logs_dir / "animetta.log"),
            rotation="1 day",
            retention="7 days",
            compression="zip",
            enqueue=True,
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        )

        # ── Redis checkpoint setup ──────────────────────────────
        _setup_checkpointer()

        # Create server
        _server = create_server(global_config)
        _server.set_user_settings(user_settings)

        # Start background model warmup (non-blocking - models load while server accepts connections)
        # warmup() is safe to call even if no services are registered yet
        logger.info("Starting background model warmup...")
        _INIT_TASKS.append(asyncio.ensure_future(_server.model_manager.warmup()))

        # Pre-warm all services so the first real user request doesn't pay cold-start cost.
        # This creates a throwaway ServiceContext that triggers all imports and model loading.
        logger.info("Starting service pre-warmup (cold-start mitigation)...")
        _INIT_TASKS.append(asyncio.ensure_future(_server.prewarm_services()))

        # ── Start daily inspection scheduler ────────────────────────
        try:

            _inspection_scheduler = InspectionScheduler(interval_hours=24)
            _INIT_TASKS.append(asyncio.ensure_future(_inspection_scheduler.start()))
            logger.info("[Inspection] Daily inspection scheduler registered")
        except Exception as e:
            logger.warning(
                f"[Inspection] Failed to start inspection scheduler (non-fatal): {e}"
            )

        asgi_app = _server.get_app()
        _INIT_DONE.set()

    return _wrap_with_frontend_serving(asgi_app)


def _wrap_with_frontend_serving(app):
    """Wrap ASGI app with frontend static file serving.

    Serves frontend/dist as static files for SPA deployment.
    Uses middleware to avoid conflicts with /socket.io/ and /api/ routes.

    Args:
        app: The original ASGI app (Socket.IO + API routes)
    Returns:
        Wrapped ASGI app with frontend serving
    """
    import mimetypes

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import FileResponse

    # Resolve frontend/dist path (project_root/frontend/dist)
    frontend_dist = _PROJECT_ROOT / "frontend" / "dist"

    if not frontend_dist.is_dir():
        logger.warning(f"[Frontend] frontend/dist not found: {frontend_dist}")
        logger.warning("[Frontend] Static file serving disabled — run 'npm run build' in frontend/")
        return app

    logger.info(f"[Frontend] Serving static files from: {frontend_dist}")

    index_html = frontend_dist / "index.html"

    class FrontendServingMiddleware(BaseHTTPMiddleware):
        """Middleware that serves frontend static files for SPA deployment.

        - /assets/* and other static files: served directly from frontend/dist
        - /api/*, /socket.io/*, /metrics: passed through to backend
        - All other paths: served index.html (SPA fallback)
        """

        async def dispatch(self, request, call_next):
            path = request.url.path

            # API and WebSocket routes — pass through to backend
            if path.startswith("/api/") or path.startswith("/socket.io") or path == "/metrics" or path == "/health":
                return await call_next(request)

            # Try to serve exact file match from frontend/dist
            file_path = frontend_dist / path.lstrip("/")
            if file_path.is_file():
                mime_type, _ = mimetypes.guess_type(str(file_path))
                return FileResponse(
                    str(file_path),
                    media_type=mime_type or "application/octet-stream",
                )

            # SPA fallback: serve index.html for all non-API, non-file routes
            # This enables client-side routing (Vue Router history mode)
            if index_html.is_file():
                return FileResponse(str(index_html), media_type="text/html")

            # No frontend built — fall through to backend
            return await call_next(request)

    app.add_middleware(FrontendServingMiddleware)
    logger.info("[Frontend] SPA middleware registered — /api/ and /socket.io/ pass through")
    return app


def _setup_checkpointer() -> None:
    """Set up the LangGraph checkpointer based on --redis-url.

    If --redis-url is given, tries to create an AsyncRedisSaver.
    On failure, or if --redis-url is absent, falls back to MemorySaver.
    """

    redis_url = _server_args.redis_url

    if not redis_url:
        logger.info("[Checkpoint] --redis-url not set, using in-memory MemorySaver")
        return  # keep default builder behavior (no external checkpointer)

    try:
        checkpointer = AsyncRedisSaver(redis_url)
        set_external_checkpointer(checkpointer)
        logger.info(f"[Checkpoint] Redis checkpointer active: {redis_url}")
    except Exception as e:
        logger.warning(
            f"[Checkpoint] Redis unavailable ({e}), "
            f"falling back to in-memory MemorySaver"
        )


if __name__ == '__main__':
    run_server()
