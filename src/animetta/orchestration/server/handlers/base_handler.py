"""
Base socket handler — shared utilities and infrastructure.

Provides the constructor pattern and shared utility methods that
other handler modules depend on (_get_or_create_orchestrator,
broadcast_to_desktop_clients, etc.).
"""

import json
from typing import TYPE_CHECKING

from animetta.config.app import AppConfig
from animetta.config.live2d import get_live2d_config

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..desktop import DesktopClientManager
    from ..live2d import Live2DManager
    from ..session import SessionManager


class BaseSocketHandler:
    """Base class for all socket event handlers.

    Owns session lifecycle, shared utilities, and mutable state
    (global_config, user_settings) that other handler modules
    may reference.
    """

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        desktop_manager: "DesktopClientManager",
        live2d_manager: "Live2DManager",
    ):
        self.sio = sio
        self.session_manager = session_manager
        self.desktop_manager = desktop_manager
        self.live2d_manager = live2d_manager

        self.global_config = None
        self.user_settings = None

    # ── Config setters ───────────────────────────────────────────────

    def set_global_config(self, config) -> None:
        """Set global config (delegated from RouteHandlers)."""
        self.global_config = config

    def set_user_settings(self, user_settings) -> None:
        """Set user settings (delegated from RouteHandlers)."""
        self.user_settings = user_settings

    # ── Shared utilities ─────────────────────────────────────────────

    def _make_send_callback(self, sid: str):
        """Create a send callback for the orchestrator."""

        async def send_callback(data):
            if isinstance(data, str):
                data = json.loads(data)
            event_type = data.get("type", "message")
            await self.sio.emit(event_type, data, to=sid)

        return send_callback

    async def _get_or_create_orchestrator(self, sid: str):
        """Get or create LangGraph orchestrator for a session."""

        config = self.global_config or AppConfig.load()
        send_callback = self._make_send_callback(sid)

        ctx = await self.session_manager.get_or_create_context(
            sid, config, send_callback
        )

        live2d_config = get_live2d_config()

        orchestrator = await self.session_manager.get_or_create_orchestrator(
            sid,
            ctx,
            send_callback,
            live2d_config,
            socketio=self.sio,
        )

        await self.session_manager.get_or_create_audio_processor(sid, ctx)

        return orchestrator

    async def broadcast_to_desktop_clients(
        self, client_type: str, event: str, data: dict
    ) -> None:
        """Broadcast message to desktop clients of a specified type."""
        sids = self.desktop_manager.get_clients_by_type(client_type)
        for sid in sids:
            await self.sio.emit(event, data, to=sid)
