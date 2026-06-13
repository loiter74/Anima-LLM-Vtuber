"""WebSocket route definitions — thin delegation layer.

All handler logic is extracted into server/handlers/ modules.
RouteHandlers acts as a facade that delegates to domain-specific handlers.
"""

from typing import TYPE_CHECKING, Any

from loguru import logger

from ..socket_events import EVENTS
from .desktop import DesktopClientManager
from .handlers.base_handler import BaseSocketHandler
from .handlers.bilibili_handlers import BilibiliHandlers
from .handlers.chat_handlers import ChatHandlers
from .handlers.config_handlers import ConfigHandlers
from .handlers.lifecycle_handlers import LifecycleHandlers
from .handlers.live2d_handlers import Live2DHandlers
from .handlers.minecraft_handlers import MinecraftHandlers
from .handlers.persona_handlers import PersonaHandlers
from .handlers.singing_handlers import SingingHandlers
from .live2d import Live2DManager


if TYPE_CHECKING:
    from socketio import AsyncServer

    from .session import SessionManager


class RouteHandlers:
    """Facade that delegates Socket.IO events to domain-specific handlers.

    Maintains the same external interface for backward compatibility.
    All handler logic lives in server/handlers/.
    """

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        desktop_manager: DesktopClientManager | None = None,
        live2d_manager: Live2DManager | None = None,
    ):
        # Infrastructure
        self.sio = sio
        self.session_manager = session_manager
        self.desktop_manager = desktop_manager or DesktopClientManager()
        self.live2d_manager = live2d_manager or Live2DManager()

        # Shared base — used by dependent handlers that need orchestrator access
        self.base = BaseSocketHandler(
            sio, session_manager, self.desktop_manager, self.live2d_manager
        )

        # Domain handlers (each owns a specific set of events)
        self.config = ConfigHandlers(
            sio, session_manager, self.desktop_manager, self.live2d_manager
        )
        self.bilibili = BilibiliHandlers(sio, session_manager, self.base)
        self.chat = ChatHandlers(sio, session_manager, self.base)
        self.live2d = Live2DHandlers(sio, self.live2d_manager, self.base)
        self.minecraft = MinecraftHandlers(sio)
        self.persona = PersonaHandlers(
            sio, session_manager, self.desktop_manager, self.live2d_manager
        )
        self.lifecycle = LifecycleHandlers(
            sio, session_manager, self.desktop_manager, self.live2d_manager
        )
        self.singing = SingingHandlers(
            sio, session_manager, self.desktop_manager, self.live2d_manager
        )

        # Backward-compat: expose global_config/user_settings from base
        self.global_config = self.base.global_config
        self.user_settings = self.base.user_settings

        # Wire up Live2D callback
        self.live2d._setup_live2d_callback()

    # ── Config setters (backward compat) ──────────────────────────────

    # ── Backward-compat properties for internal state moved to handlers ─

    @property
    def _bilibili_service(self):
        """Backward-compat: Bilibili danmaku service (now on BilibiliHandlers)."""
        return self.bilibili._bilibili_service

    @_bilibili_service.setter
    def _bilibili_service(self, value):
        self.bilibili._bilibili_service = value

    @property
    def _main_loop(self):
        """Backward-compat: main event loop (now on BilibiliHandlers)."""
        return self.bilibili._main_loop

    @_main_loop.setter
    def _main_loop(self, value):
        self.bilibili._main_loop = value

    # ── Config setters (backward compat) ──────────────────────────────

    def set_global_config(self, config) -> None:
        """Set global config — delegates to domain handlers."""
        self.base.set_global_config(config)
        self.global_config = self.base.global_config
        for h in [self.config, self.persona, self.lifecycle]:
            h.global_config = config

    def set_user_settings(self, user_settings) -> None:
        """Set user settings — delegates to domain handlers."""
        self.base.set_user_settings(user_settings)
        self.user_settings = self.base.user_settings
        for h in [self.config, self.persona, self.lifecycle]:
            h.user_settings = user_settings

    # ── Shared utility (backward compat) ─────────────────────────────

    async def broadcast_to_desktop_clients(
        self, client_type: str, event: str, data: dict
    ) -> None:
        """Broadcast to desktop clients — delegates to BaseSocketHandler."""
        return await self.base.broadcast_to_desktop_clients(
            client_type, event, data
        )

    # ── Bilibili service (backward compat — called by WebSocketServer) ─

    def start_bilibili(self, room_id: int, sessdata: str = "") -> None:
        """Start Bilibili danmaku service — delegates to BilibiliHandlers."""
        return self.bilibili.start_bilibili(room_id, sessdata)

    def stop_bilibili(self) -> None:
        """Stop Bilibili danmaku service — delegates to BilibiliHandlers."""
        return self.bilibili.stop_bilibili()

    # ── Connection events ─────────────────────────────────────────────

    async def on_connect(self, sid: str, environ: dict) -> None:
        return await self.lifecycle.on_connect(sid, environ)

    async def on_disconnect(self, sid: str) -> None:
        return await self.lifecycle.on_disconnect(sid)

    # ── Conversation events ───────────────────────────────────────────

    async def on_text_input(self, sid: str, data: dict) -> None:
        return await self.chat.on_text_input(sid, data)

    async def on_raw_audio_data(self, sid: str, data: dict) -> None:
        return await self.chat.on_raw_audio_data(sid, data)

    async def on_mic_audio_end(self, sid: str, data: dict) -> None:
        return await self.chat.on_mic_audio_end(sid, data)

    async def on_interrupt_signal(self, sid: str, data: dict) -> None:
        return await self.chat.on_interrupt_signal(sid, data)

    # ── History events ────────────────────────────────────────────────

    async def on_fetch_history_list(self, sid: str, data: dict) -> None:
        return await self.chat.on_fetch_history_list(sid, data)

    async def on_fetch_history(self, sid: str, data: dict) -> None:
        return await self.chat.on_fetch_history(sid, data)

    async def on_clear_history(self, sid: str, data: dict) -> None:
        return await self.chat.on_clear_history(sid, data)

    async def on_create_new_history(self, sid: str, data: dict) -> None:
        return await self.chat.on_create_new_history(sid, data)

    # ── Config events ─────────────────────────────────────────────────

    async def on_switch_config(self, sid: str, data: dict) -> None:
        return await self.config.on_switch_config(sid, data)

    async def on_set_log_level(self, sid: str, data: dict) -> None:
        return await self.config.on_set_log_level(sid, data)

    async def on_get_config(self, sid: str, data: dict) -> None:
        return await self.config.on_get_config(sid, data)

    # ── Heartbeat ─────────────────────────────────────────────────────

    async def on_heartbeat(self, sid: str, data: dict) -> None:
        return await self.config.on_heartbeat(sid, data)

    # ── Desktop client events ─────────────────────────────────────────

    async def on_desktop_register(self, sid: str, data: dict) -> None:
        return await self.live2d.on_desktop_register(sid, data)

    async def on_desktop_live2d_action(self, sid: str, data: dict) -> None:
        return await self.live2d.on_desktop_live2d_action(sid, data)

    async def on_desktop_chat_message(self, sid: str, data: dict) -> None:
        return await self.live2d.on_desktop_chat_message(sid, data)

    async def on_desktop_voice_start(self, sid: str, data: dict) -> None:
        return await self.live2d.on_desktop_voice_start(sid, data)

    async def on_desktop_voice_stop(self, sid: str, data: dict) -> None:
        return await self.live2d.on_desktop_voice_stop(sid, data)

    # ── Bilibili frontend control events ──────────────────────────────

    async def on_bilibili_connect(self, sid: str, data: dict) -> None:
        return await self.bilibili.on_bilibili_connect(sid, data)

    async def on_bilibili_disconnect(self, sid: str, data: dict) -> None:
        return await self.bilibili.on_bilibili_disconnect(sid, data)

    async def on_bilibili_update_room(self, sid: str, data: dict) -> None:
        return await self.bilibili.on_bilibili_update_room(sid, data)

    # ── Minecraft bot control events ───────────────────────────────────

    async def on_minecraft_start(self, sid: str, data: dict) -> None:
        return await self.minecraft.on_minecraft_start(sid, data)

    async def on_minecraft_stop(self, sid: str, data: dict) -> None:
        return await self.minecraft.on_minecraft_stop(sid, data)

    # ── Persona events ────────────────────────────────────────────────

    async def on_translation_configure(self, sid: str, data: dict) -> None:
        return await self.config.on_translation_configure(sid, data)

    async def on_get_available_personas(self, sid: str, data: dict) -> dict:
        return await self.persona.on_get_available_personas(sid, data)

    async def on_set_persona(self, sid: str, data: dict) -> None:
        return await self.persona.on_set_persona(sid, data)

    async def on_set_personality_mode(self, sid: str, data: dict) -> None:
        return await self.persona.on_set_personality_mode(sid, data)

    # ── Singing events ────────────────────────────────────────────────

    async def on_sing_process(self, sid: str, data: dict) -> None:
        return await self.singing.on_sing_process(sid, data)

    async def on_sing_confirm_lyrics(self, sid: str, data: dict) -> None:
        return await self.singing.on_sing_confirm_lyrics(sid, data)

    async def on_sing_cancel(self, sid: str, data: dict) -> None:
        return await self.singing.on_sing_cancel(sid, data)

    async def on_sing_subtitle_sync(self, sid: str, data: dict) -> None:
        return await self.singing.on_sing_subtitle_sync(sid, data)

    # ── Memory / Wiki (V2 bridge) ────────────────────────────────────

    async def on_memory_organize(self, sid: str, data: dict) -> None:
        """Trigger V2 memory metabolism + compile, emit progress."""
        try:
            ctx = await self.session_manager.get_or_create_context(
                sid, self.global_config, self._make_send_callback(sid)
            )
            mem = getattr(ctx, "memory_system", None)
            if not mem:
                await self.sio.emit(EVENTS["memory"]["organize_result"]["name"],
                    {"status": "error", "message": "Memory system not available"}, to=sid)
                return

            await self.sio.emit(EVENTS["memory"]["organize_progress"]["name"],
                {"text": "Running metabolism tick...", "progress": 30}, to=sid)
            await mem._run_metabolism_tick()

            await self.sio.emit(EVENTS["memory"]["organize_progress"]["name"],
                {"text": "Compiling RAW → EPISODIC...", "progress": 60}, to=sid)

            await self.sio.emit(EVENTS["memory"]["organize_result"]["name"],
                {"status": "ok", "message": "Memory organized"}, to=sid)
        except Exception as e:
            await self.sio.emit(EVENTS["memory"]["organize_result"]["name"],
                {"status": "error", "message": str(e)}, to=sid)

    async def on_get_wiki_pages(self, sid: str, data: dict) -> dict:
        """Return memory atoms as wiki page data for frontend."""
        try:
            ctx = await self.session_manager.get_or_create_context(
                sid, self.global_config, self._make_send_callback(sid)
            )
            mem = getattr(ctx, "memory_system", None)
            if not mem:
                return {"pages": [], "error": "Memory system not available"}

            atoms = await mem.store.get_all_active(limit=50)
            pages = []
            for a in atoms:
                # Map layer to page_type for frontend compatibility
                layer_to_type = {
                    "RAW": "source",
                    "EPISODIC": "entity",
                    "SEMANTIC": "concept",
                    "EMERGENT": "synthesis",
                }
                pages.append({
                    "path": a.id,
                    "title": a.summary or a.content[:80],
                    "content": a.content,
                    "page_type": layer_to_type.get(a.layer.name, a.layer.name.lower()),
                    "tags": a.tags or [],
                    "updated_at": (a.rewritten_at or a.occurred_at).isoformat() if (a.rewritten_at or a.occurred_at) else "",
                })
            return {"pages": pages}
        except Exception as e:
            return {"pages": [], "error": str(e)}


def register_routes(
    sio: "AsyncServer",
    session_manager: "SessionManager",
    desktop_manager: DesktopClientManager | None = None,
    live2d_manager: Live2DManager | None = None,
    bilibili_config: dict[str, Any] | None = None,
) -> RouteHandlers:
    """Register all routes to the Socket.IO server."""
    handlers = RouteHandlers(
        sio, session_manager, desktop_manager, live2d_manager
    )

    # Start Bilibili danmaku service if configured
    if bilibili_config and bilibili_config.get("enabled", False):
        room_id = bilibili_config.get("room_id")
        if room_id:
            handlers.bilibili.start_bilibili(
                room_id=int(room_id),
                sessdata=bilibili_config.get("sessdata", ""),
            )

    # Connection events
    sio.on("connect", handlers.on_connect)
    sio.on("disconnect", handlers.on_disconnect)

    # Conversation events
    sio.on(EVENTS.get("chat", {}).get("text", {}).get("name", "chat:text"), handlers.on_text_input)
    sio.on(EVENTS.get("chat", {}).get("audio", {}).get("name", "chat:audio"), handlers.on_raw_audio_data)
    sio.on(EVENTS.get("chat", {}).get("audio_end", {}).get("name", "chat:audio_end"), handlers.on_mic_audio_end)
    sio.on(EVENTS.get("chat", {}).get("interrupt", {}).get("name", "chat:interrupt"), handlers.on_interrupt_signal)

    # History events
    sio.on(EVENTS.get("history", {}).get("list", {}).get("name", "history:list"), handlers.on_fetch_history_list)
    sio.on(EVENTS.get("history", {}).get("fetch", {}).get("name", "history:fetch"), handlers.on_fetch_history)
    sio.on(EVENTS.get("history", {}).get("clear", {}).get("name", "history:clear"), handlers.on_clear_history)
    sio.on(EVENTS.get("history", {}).get("create", {}).get("name", "history:create"), handlers.on_create_new_history)

    # Config events
    sio.on(EVENTS.get("config", {}).get("switch", {}).get("name", "config:switch"), handlers.on_switch_config)
    sio.on(EVENTS.get("config", {}).get("log_level", {}).get("name", "config:log_level"), handlers.on_set_log_level)
    sio.on(EVENTS.get("config", {}).get("get", {}).get("name", "config:get"), handlers.on_get_config)

    # Heartbeat
    sio.on(EVENTS.get("system", {}).get("heartbeat", {}).get("name", "system:heartbeat"), handlers.on_heartbeat)

    # Desktop client events
    sio.on(EVENTS.get("desktop", {}).get("register", {}).get("name", "desktop:register"), handlers.on_desktop_register)
    sio.on(EVENTS.get("desktop", {}).get("live2d_action", {}).get("name", "desktop:live2d_action"), handlers.on_desktop_live2d_action)
    sio.on(EVENTS.get("desktop", {}).get("chat_message", {}).get("name", "desktop:chat_message"), handlers.on_desktop_chat_message)
    sio.on(EVENTS.get("desktop", {}).get("voice_start", {}).get("name", "desktop:voice_start"), handlers.on_desktop_voice_start)
    sio.on(EVENTS.get("desktop", {}).get("voice_stop", {}).get("name", "desktop:voice_stop"), handlers.on_desktop_voice_stop)

    # Bilibili frontend control events
    sio.on(EVENTS.get("bilibili", {}).get("connect", {}).get("name", "bilibili:connect"), handlers.on_bilibili_connect)
    sio.on(EVENTS.get("bilibili", {}).get("disconnect", {}).get("name", "bilibili:disconnect"), handlers.on_bilibili_disconnect)
    sio.on(EVENTS.get("bilibili", {}).get("update_room", {}).get("name", "bilibili:update_room"), handlers.on_bilibili_update_room)

    # Minecraft bot control events
    sio.on(EVENTS.get("minecraft", {}).get("start", {}).get("name", "minecraft:start"), handlers.on_minecraft_start)
    sio.on(EVENTS.get("minecraft", {}).get("stop", {}).get("name", "minecraft:stop"), handlers.on_minecraft_stop)

    # Translation configuration events
    sio.on(EVENTS.get("translation", {}).get("configure", {}).get("name", "translation:configure"), handlers.on_translation_configure)

    # Persona runtime switching
    sio.on(EVENTS.get("persona", {}).get("list", {}).get("name", "persona:list"), handlers.on_get_available_personas)
    sio.on(EVENTS.get("persona", {}).get("set", {}).get("name", "persona:set"), handlers.on_set_persona)

    # Personality mode runtime switching
    sio.on(EVENTS.get("persona", {}).get("set_mode", {}).get("name", "persona:set_mode"), handlers.on_set_personality_mode)

    # Singing module events
    sio.on(EVENTS.get("sing", {}).get("process", {}).get("name", "sing:process"), handlers.on_sing_process)
    sio.on(EVENTS.get("sing", {}).get("confirm_lyrics", {}).get("name", "sing:confirm_lyrics"), handlers.on_sing_confirm_lyrics)
    sio.on(EVENTS.get("sing", {}).get("cancel", {}).get("name", "sing:cancel"), handlers.on_sing_cancel)
    sio.on(EVENTS.get("sing", {}).get("subtitle_sync", {}).get("name", "sing:subtitle_sync"), handlers.on_sing_subtitle_sync)

    # Memory: wiki pages (legacy compat — delegates to V2)
    sio.on(EVENTS.get("memory", {}).get("organize", {}).get("name", "memory:organize"), handlers.on_memory_organize)
    sio.on(EVENTS.get("memory", {}).get("list_pages", {}).get("name", "memory:list_pages"), handlers.on_get_wiki_pages)

    logger.info("WebSocket routes registered")
    return handlers
