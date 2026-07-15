"""
Live2D and desktop client event handlers.

Manages Live2D action execution callbacks and handles
desktop (Electron) client registration and events.
"""

from typing import TYPE_CHECKING

from loguru import logger

from ...socket_events import EVENTS

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..live2d import Live2DManager
    from .base_handler import BaseSocketHandler


class Live2DHandlers:
    """Live2D and desktop client event handlers.

    Receives sio, live2d_manager, and a reference to BaseSocketHandler
    for shared utilities like broadcast_to_desktop_clients and
    _get_or_create_orchestrator.
    """

    def __init__(
        self,
        sio: "AsyncServer",
        live2d_manager: "Live2DManager",
        admin: "BaseSocketHandler",
    ):
        self.sio = sio
        self.live2d_manager = live2d_manager
        self.admin = admin

    # ── Live2D callback setup ─────────────────────────────────────────

    def _setup_live2d_callback(self) -> None:
        """Set up Live2D action execution callback.

        Creates the execute_action closure and registers it
        with the Live2DManager so that queued actions are
        broadcast to desktop clients.
        """

        async def execute_action(action):
            await self.admin.broadcast_to_desktop_clients(
                "live2d",
                "live2d:action",
                {
                    "action": action.action,
                    "action_id": action.action_id,
                },
            )

        self.live2d_manager.set_execute_callback(execute_action)

    # ── Desktop client events ─────────────────────────────────────────

    async def on_desktop_register(self, sid: str, data: dict) -> None:
        """Electron desktop client registration."""
        client_type = data.get("client_type", "web")

        if not self.admin.desktop_manager.register(sid, client_type):
            await self.sio.emit(
                EVENTS["system"]["error"]["name"],
                {"type": "error", "message": f"Unknown client type: {client_type}"},
                to=sid,
            )
            return

        await self.sio.emit(
            EVENTS["desktop"]["registered"]["name"],
            {"client_id": sid, "client_type": client_type},
            to=sid,
        )

    async def on_desktop_live2d_action(self, sid: str, data: dict) -> None:
        """Handle Live2D action request from Electron."""
        action_data = data.get("action", {})
        action_id = data.get("action_id", "")
        queue_policy = data.get("queue_policy", "append")
        duration = data.get("duration", 0.5)

        result = await self.live2d_manager.enqueue_action(
            action_data=action_data,
            action_id=action_id,
            queue_policy=queue_policy,
            duration=duration,
        )

        await self.sio.emit(EVENTS["desktop"]["action_queued"]["name"], result, to=sid)

    async def on_desktop_chat_message(self, sid: str, data: dict) -> None:
        """Handle chat message from Electron Chat window."""
        text = data.get("text", "")
        logger.info(f"[Desktop][Chat] Received message: {text[:50]}...")

        try:
            orchestrator = await self.admin._get_or_create_orchestrator(sid)
            await orchestrator.process_text(
                text=text,
                user_id="user",
                user_name="User",
                channel_id=sid,
            )

        except Exception as e:
            logger.error(f"[{sid}] Error processing desktop chat message: {e}")
            await self.sio.emit(
                EVENTS["system"]["error"]["name"], {"type": "error", "message": str(e)}, to=sid
            )

    async def on_desktop_voice_start(self, sid: str, data: dict) -> None:
        """Start voice input."""
        logger.info("[Desktop][Chat] Voice input started")
        await self.sio.emit(EVENTS["desktop"]["voice_started"]["name"], {}, to=sid)

    async def on_desktop_voice_stop(self, sid: str, data: dict) -> None:
        """Stop voice input."""
        logger.info("[Desktop][Chat] Voice input stopped")
        await self.sio.emit(EVENTS["desktop"]["voice_stopped"]["name"], {}, to=sid)
