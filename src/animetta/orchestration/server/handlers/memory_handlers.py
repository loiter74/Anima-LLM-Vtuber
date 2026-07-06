"""
Memory event handlers — V2 memory maintenance and wiki page bridge.
"""

from typing import TYPE_CHECKING

from loguru import logger

from ...socket_events import EVENTS
from .base_handler import BaseSocketHandler

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..session import SessionManager


class MemoryHandlers(BaseSocketHandler):
    """Memory and wiki event handlers.

    These routes need the shared BaseSocketHandler context factory so they use
    the same runtime config boundary as chat/orchestrator setup.
    """

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        base: BaseSocketHandler,
    ):
        self._base = base
        self._global_config = None
        super().__init__(sio, session_manager, base.desktop_manager, base.live2d_manager)

    @property
    def global_config(self):
        if self._base and self._base.global_config:
            return self._base.global_config
        return self._global_config

    @global_config.setter
    def global_config(self, value) -> None:
        self._global_config = value
        if self._base:
            self._base.global_config = value

    async def _get_context(self, sid: str):
        return await self._base.get_or_create_context(sid)

    async def on_memory_organize(self, sid: str, data: dict) -> None:
        """Trigger V2 memory metabolism + compile, emit progress."""
        try:
            ctx = await self._get_context(sid)
            mem = getattr(ctx, "memory_system", None)
            if not mem:
                await self.sio.emit(
                    EVENTS["memory"]["organize_result"]["name"],
                    {"status": "error", "message": "Memory system not available"},
                    to=sid,
                )
                return

            await self.sio.emit(
                EVENTS["memory"]["organize_progress"]["name"],
                {"text": "Running metabolism tick...", "progress": 30},
                to=sid,
            )
            await mem.run_metabolism_tick()

            await self.sio.emit(
                EVENTS["memory"]["organize_progress"]["name"],
                {"text": "Compiling RAW → EPISODIC...", "progress": 60},
                to=sid,
            )

            await self.sio.emit(
                EVENTS["memory"]["organize_result"]["name"],
                {"status": "ok", "message": "Memory organized"},
                to=sid,
            )
        except Exception as e:
            await self.sio.emit(
                EVENTS["memory"]["organize_result"]["name"],
                {"status": "error", "message": str(e)},
                to=sid,
            )

    async def on_get_wiki_pages(self, sid: str, data: dict) -> dict:
        """Return memory atoms as wiki page data for frontend."""
        try:
            ctx = await self._get_context(sid)
            mem = getattr(ctx, "memory_system", None)
            if not mem:
                logger.warning(f"[wiki_pages] memory_system is None for sid={sid}")
                return {"pages": [], "error": "Memory system not available"}

            pages = await mem.list_wiki_pages(limit=50)
            logger.info(f"[wiki_pages] sid={sid} pages={len(pages)}")
            return {"pages": pages}
        except Exception as e:
            logger.exception(f"[wiki_pages] ERROR: {e}")
            return {"pages": [], "error": str(e)}
