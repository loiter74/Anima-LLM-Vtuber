"""
Connection lifecycle event handlers — connect, disconnect.
"""

import asyncio
import time
from typing import TYPE_CHECKING

from loguru import logger

from ...socket_events import EVENTS
from .base_handler import BaseSocketHandler

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..desktop import DesktopClientManager
    from ..live2d import Live2DManager
    from ..session import SessionManager


class LifecycleHandlers(BaseSocketHandler):
    """Connection and disconnection event handlers.

    Inherits shared infrastructure from BaseSocketHandler.
    """

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        desktop_manager: "DesktopClientManager",
        live2d_manager: "Live2DManager",
    ):
        super().__init__(sio, session_manager, desktop_manager, live2d_manager)

    # ── Connection events ────────────────────────────────────────────

    async def on_connect(self, sid: str, environ: dict) -> None:
        """Client connection event."""
        client_type = environ.get("HTTP_USER_AGENT", "")
        is_electron = "electron" in client_type.lower()

        print(f"\n{'=' * 60}")
        print(f"[OK] Client connected: {sid}")
        print(f"     Type: {'Electron' if is_electron else 'Web'}")
        print(f"{'=' * 60}\n")
        logger.info(
            f"Client connected: {sid} (Type: {'Electron' if is_electron else 'Web'})"
        )

        await self.sio.save_session(
            sid, {"connected_at": time.time(), "is_electron": is_electron}
        )

        await self.sio.emit(
            EVENTS["system"]["connection_established"]["name"],
            {
                "message": "Connection successful",
                "sid": sid,
                "server_time": asyncio.get_event_loop().time(),
            },
            to=sid,
        )

        # OTel metrics: active sessions gauge
        try:

            g = get_active_sessions()
            if g is not None:
                g.add(1)
        except Exception as e:
            logger.debug(f"[LifecycleHandlers] OTel active_sessions (add) failed: {e}")

        if not is_electron:
            await self.sio.emit(
                EVENTS["chat"]["control"]["name"], {"type": "control", "text": "start-mic"}, to=sid
            )
            print(f"[OK] Sent start-mic signal to client {sid}")

    async def on_disconnect(self, sid: str) -> None:
        """Client disconnect event."""
        logger.info(f"Client disconnected: {sid}")
        self.desktop_manager.unregister(sid)
        await self.session_manager.cleanup_session(sid)

        # OTel metrics: active sessions gauge
        try:

            g = get_active_sessions()
            if g is not None:
                g.add(-1)
        except Exception as e:
            logger.debug(f"[LifecycleHandlers] OTel active_sessions (sub) failed: {e}")
