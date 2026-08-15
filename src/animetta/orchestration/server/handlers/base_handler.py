"""
Base socket handler — shared utilities and infrastructure.

Provides the constructor pattern and shared utility methods that
other handler modules depend on (_get_or_create_orchestrator,
broadcast_to_desktop_clients, etc.).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from animetta.config.live2d import get_live2d_config
from animetta.config.manifest import EffectiveConfig
from animetta.config.user import UserSettings

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ....core.service_context import ServiceContext
    from ...graph.orchestrator import LangGraphOrchestrator
    from ..desktop import DesktopClientManager
    from ..live2d import Live2DManager
    from ..session import SessionManager

SendCallback = Callable[[dict[str, Any] | str], Awaitable[None]]


class BaseSocketHandler:
    """Base class for all socket event handlers.

    Owns session lifecycle, shared utilities, and mutable state
    (global_config, user_settings) that other handler modules
    may reference.
    """

    def __init__(
        self,
        sio: AsyncServer,
        session_manager: SessionManager,
        desktop_manager: DesktopClientManager,
        live2d_manager: Live2DManager,
    ):
        self.sio = sio
        self.session_manager = session_manager
        self.desktop_manager = desktop_manager
        self.live2d_manager = live2d_manager
        self.live_session_id = str(uuid4())

        self.global_config: EffectiveConfig | None = None
        self.user_settings: UserSettings | None = None

    # ── Config setters ───────────────────────────────────────────────

    def set_global_config(self, config: EffectiveConfig) -> None:
        """Set global config (delegated from RouteHandlers)."""
        self.global_config = config

    def set_user_settings(self, user_settings: UserSettings) -> None:
        """Set user settings (delegated from RouteHandlers)."""
        self.user_settings = user_settings

    # ── Shared utilities ─────────────────────────────────────────────

    def make_send_callback(self, sid: str) -> SendCallback:
        """Create a send callback for the orchestrator."""

        async def send_callback(data: dict[str, Any] | str) -> None:
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict):
                raise TypeError("Socket send callback payload must be an object")
            event_type = data.get("type", "message")
            await self.sio.emit(event_type, data, to=sid)

        return send_callback

    def _make_send_callback(self, sid: str):
        """Deprecated compatibility wrapper for old internal callers."""
        return self.make_send_callback(sid)

    def get_active_config(self) -> EffectiveConfig:
        """Return the one bootstrap snapshot; handlers never reload independently."""
        if self.global_config is None:
            raise RuntimeError("Runtime EffectiveConfig has not been published")
        return self.global_config

    async def get_or_create_context(
        self,
        sid: str,
        send_callback: SendCallback | None = None,
    ) -> ServiceContext:
        """Create a session context using the shared handler config boundary."""
        send_callback = send_callback or self.make_send_callback(sid)
        return await self.session_manager.get_or_create_context(
            sid, self.get_active_config(), send_callback
        )

    async def get_or_create_orchestrator(self, sid: str) -> LangGraphOrchestrator:
        """Get or create LangGraph orchestrator for a session."""

        send_callback = self.make_send_callback(sid)

        ctx = await self.get_or_create_context(sid, send_callback)

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

    async def _get_or_create_orchestrator(self, sid: str) -> LangGraphOrchestrator:
        """Deprecated compatibility wrapper for domain handlers."""
        return await self.get_or_create_orchestrator(sid)

    async def broadcast_to_desktop_clients(self, client_type: str, event: str, data: dict) -> None:
        """Broadcast message to desktop clients of a specified type."""
        sids = self.desktop_manager.get_clients_by_type(client_type)
        for sid in sids:
            await self.sio.emit(event, data, to=sid)
