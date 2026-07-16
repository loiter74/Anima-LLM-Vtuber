"""
Standalone ASGI application for the Notifier service.

Provides a single endpoint: POST /api/v1/alerts
which accepts Alertmanager webhook payloads and routes them
to enabled notification channels.
"""

import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .manager import NotifierManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_manager: NotifierManager | None = None


def _get_manager() -> NotifierManager:
    global _manager
    if _manager is None:
        import contextlib

        # Import plugins so they self-register
        with contextlib.suppress(ImportError):
            import animetta.notifier.discord  # noqa: F401
        with contextlib.suppress(ImportError):
            import animetta.notifier.feishu  # noqa: F401
        with contextlib.suppress(ImportError):
            import animetta.notifier.email  # noqa: F401
        _manager = NotifierManager()
    return _manager


async def handle_alert(request: Request) -> JSONResponse:
    """POST /api/v1/alerts — receive Alertmanager webhook payload."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    try:
        manager = _get_manager()
        results = await manager.handle(payload)
        return JSONResponse({"status": "ok", "channels": results})
    except Exception as e:
        logger.exception("Alert handling failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def health(request: Request) -> JSONResponse:
    """GET /health — liveness check."""
    return JSONResponse({"status": "ok", "service": "anima-notifier"})


def create_notifier_app() -> Starlette:
    """Create the standalone Starlette ASGI app."""
    app = Starlette(
        routes=[
            Route("/health", health),
            Route("/api/v1/alerts", handle_alert, methods=["POST"]),
        ]
    )
    return app
