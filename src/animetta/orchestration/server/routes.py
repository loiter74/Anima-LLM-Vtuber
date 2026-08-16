"""WebSocket route definitions — thin delegation layer.

All handler logic is extracted into server/handlers/ modules.
RouteHandlers acts as a facade that delegates to domain-specific handlers.
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger
from socketio.exceptions import ConnectionRefusedError

from animetta.config.manifest import EffectiveConfig
from animetta.config.user import UserSettings
from animetta.orchestration.graph.checkpointing import CheckpointRequest
from animetta.services.command_inbox import (
    ACTIVE_STATUSES,
    CommandInbox,
    CommandInboxError,
    CommandKey,
)

from ..socket_events import EVENTS, event_aliases, event_name
from .auth_session import AuthSessionStoreUnavailableError
from .desktop import DesktopClientManager
from .handlers.base_handler import BaseSocketHandler
from .handlers.bilibili_handlers import BilibiliHandlers
from .handlers.chat_handlers import ChatHandlers
from .handlers.config_handlers import ConfigHandlers
from .handlers.lifecycle_handlers import LifecycleHandlers
from .handlers.live2d_handlers import Live2DHandlers
from .handlers.meme_handlers import MemeHandlers
from .handlers.memory_handlers import MemoryHandlers
from .handlers.minecraft_handlers import MinecraftHandlers
from .handlers.persona_handlers import PersonaHandlers
from .handlers.singing_handlers import SingingHandlers
from .live2d import Live2DManager
from .security import RateLimitError, SecurityRuntime

if TYPE_CHECKING:
    from socketio import AsyncServer

    from animetta.observability.ports import (
        ObservationQuery,
        ObservationRecorder,
        ObservationReportStore,
    )

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
        observation_recorder: "ObservationRecorder | None" = None,
        observation_query: "ObservationQuery | None" = None,
        observation_report_store: "ObservationReportStore | None" = None,
        command_inbox: CommandInbox | None = None,
    ):
        # Infrastructure
        self.sio = sio
        self.session_manager = session_manager
        self.desktop_manager = desktop_manager or DesktopClientManager()
        self.live2d_manager = live2d_manager or Live2DManager()
        self.observation_recorder = observation_recorder
        self.observation_query = observation_query
        self.observation_report_store = observation_report_store
        self.command_inbox = command_inbox or CommandInbox(":memory:")

        # Shared base — used by dependent handlers that need orchestrator access
        self.base = BaseSocketHandler(
            sio, session_manager, self.desktop_manager, self.live2d_manager
        )

        # Domain handlers (each owns a specific set of events)
        self.config_handlers = ConfigHandlers(
            sio, session_manager, self.desktop_manager, self.live2d_manager
        )
        self.bilibili = BilibiliHandlers(sio, session_manager, self.base)
        self.chat = ChatHandlers(sio, session_manager, self.base, self.command_inbox)
        self.live2d = Live2DHandlers(sio, self.live2d_manager, self.base)
        self.memory = MemoryHandlers(sio, session_manager, self.base, self.command_inbox)
        self.meme = MemeHandlers(sio, session_manager, self.base, self.command_inbox)
        self.minecraft = MinecraftHandlers(sio)
        self.persona = PersonaHandlers(
            sio, session_manager, self.desktop_manager, self.live2d_manager, self.base
        )
        self.lifecycle = LifecycleHandlers(
            sio, session_manager, self.desktop_manager, self.live2d_manager
        )
        self.singing = SingingHandlers(
            sio,
            session_manager,
            self.desktop_manager,
            self.live2d_manager,
            self.command_inbox,
        )

        # Wire up Live2D callback
        self.live2d._setup_live2d_callback()

    # ── Config setters (backward compat) ──────────────────────────────

    # ── Backward-compat properties for internal state moved to handlers ─

    @property
    def global_config(self) -> EffectiveConfig | None:
        """Backward-compat: shared config now lives on BaseSocketHandler."""
        return self.base.global_config

    @global_config.setter
    def global_config(self, value: EffectiveConfig | None) -> None:
        self.base.global_config = value
        for handler in self._domain_handlers():
            handler.global_config = value

    @property
    def user_settings(self) -> UserSettings | None:
        """Backward-compat: shared user settings now live on BaseSocketHandler."""
        return self.base.user_settings

    @user_settings.setter
    def user_settings(self, value: UserSettings | None) -> None:
        self.base.user_settings = value
        for handler in self._domain_handlers():
            if hasattr(handler, "user_settings"):
                handler.user_settings = value

    def _domain_handlers(self) -> list[Any]:
        return [
            self.config_handlers,
            self.bilibili,
            self.chat,
            self.live2d,
            self.memory,
            self.meme,
            self.minecraft,
            self.persona,
            self.lifecycle,
            self.singing,
        ]

    @property
    def _bilibili_service(self):
        """Backward-compat: Bilibili danmaku service (now on BilibiliHandlers)."""
        return self.bilibili._bilibili_service

    @_bilibili_service.setter
    def _bilibili_service(self, value: Any) -> None:
        self.bilibili._bilibili_service = value

    @property
    def _main_loop(self) -> asyncio.AbstractEventLoop | None:
        """Backward-compat: main event loop (now on BilibiliHandlers)."""
        return self.bilibili._main_loop

    @_main_loop.setter
    def _main_loop(self, value: asyncio.AbstractEventLoop | None) -> None:
        self.bilibili._main_loop = value

    # ── Config setters (backward compat) ──────────────────────────────

    def set_global_config(self, config: EffectiveConfig) -> None:
        """Set global config — delegates to domain handlers."""
        self.global_config = config
        scene_analysis = getattr(config, "scene_analysis", None)
        if scene_analysis is not None:
            self.bilibili.configure_scene_analysis(scene_analysis)

    def set_user_settings(self, user_settings: UserSettings) -> None:
        """Set user settings — delegates to domain handlers."""
        self.user_settings = user_settings

    # ── Shared utility (backward compat) ─────────────────────────────

    async def broadcast_to_desktop_clients(self, client_type: str, event: str, data: dict) -> None:
        """Broadcast to desktop clients — delegates to BaseSocketHandler."""
        return await self.base.broadcast_to_desktop_clients(client_type, event, data)

    # ── Bilibili service (backward compat — called by WebSocketServer) ─

    async def start_bilibili(
        self,
        room_id: int,
        sessdata: str | None = None,
    ) -> dict[str, Any]:
        """Start Bilibili danmaku service — delegates to BilibiliHandlers."""
        return await self.bilibili.start_bilibili(room_id, sessdata)

    async def stop_bilibili(self) -> dict[str, Any]:
        """Stop Bilibili danmaku service — delegates to BilibiliHandlers."""
        return await self.bilibili.stop_bilibili()

    async def start_runtime(self) -> None:
        """Start async domain runtimes during the ASGI lifespan."""
        await self.command_inbox.start()
        await self.meme.restore_latest_collection()
        await self.bilibili.start_configured()

    async def stop_runtime(self) -> None:
        """Stop async domain runtimes during server shutdown."""
        await self.singing.shutdown()
        await self.bilibili.stop_bilibili()

    async def on_task_status(self, sid: str, data: dict) -> dict[str, Any]:
        """Return a durable task snapshot without trusting a client-supplied scope."""
        kind = str(data.get("kind") or "").strip()
        task_id = str(data.get("task_id") or "").strip()
        context = data.get("scope_context")
        context = context if isinstance(context, dict) else {}
        conversation_id = str(context.get("conversation_id") or "").strip()
        audience = str(context.get("audience") or "").strip()
        if not kind or not task_id:
            return _task_error("INVALID_REQUEST", "kind and task_id are required")
        public_kinds = {
            "chat.public",
            "chat.sandbox",
            "singing.process",
            "meme.collect",
            "memory.change",
            "memory.organize",
            "program.start",
            "program.choice",
            "program.control",
            "replay.start",
            "replay.control",
        }
        if kind not in public_kinds:
            return _task_error("INVALID_REQUEST", "unknown task kind")
        if kind == "chat.public":
            if audience == "livestream":
                scope = f"stream:{self.base.live_session_id}"
            elif not conversation_id:
                return _task_error("INVALID_REQUEST", "conversation_id is required")
            else:
                scope = f"conversation:{conversation_id}"
        elif kind == "chat.sandbox":
            if not conversation_id:
                return _task_error("INVALID_REQUEST", "conversation_id is required")
            scope = f"sandbox:{conversation_id}"
        else:
            scope = "dashboard"
        accepted = await self.command_inbox.get(CommandKey(scope, kind, task_id))
        if accepted.task is None:
            return _task_error("TASK_NOT_FOUND", "task not found")
        if accepted.task.status in ACTIVE_STATUSES:
            if kind == "chat.sandbox":
                self.chat.observe_sandbox(sid, task_id)
            elif kind == "singing.process":
                self.singing.observe(sid, task_id)
            elif kind == "meme.collect":
                self.meme.observe_collection(sid, task_id)
            elif kind == "memory.organize":
                self.memory.observe_organize(sid, task_id)
        snapshot = accepted.task.snapshot(reused=True)
        await self.sio.emit(EVENTS["task"]["snapshot"]["name"], snapshot, to=sid)
        return {"ok": True, "data": snapshot}

    async def on_tool_approval_list(
        self,
        sid: str,
        data: dict | None = None,
    ) -> dict[str, Any]:
        del sid, data
        tasks = await self.command_inbox.waiting_approvals()
        return {"ok": True, "approvals": [_approval_snapshot(task) for task in tasks]}

    async def on_tool_approval_decide(self, sid: str, data: dict) -> dict[str, Any]:
        if not isinstance(data, dict):
            return _task_error("INVALID_REQUEST", "approval decision must be an object")
        if set(data) - {"approval_id", "decision"}:
            return _task_error("INVALID_REQUEST", "approval parameters cannot be edited")
        approval_id = str(data.get("approval_id") or "").strip()
        decision = str(data.get("decision") or "").strip()
        if not approval_id or decision not in {"approve", "reject"}:
            return _task_error("INVALID_REQUEST", "approval_id and approve/reject are required")
        task = next(
            (
                item
                for item in await self.command_inbox.waiting_approvals()
                if (item.progress or {}).get("approval_id") == approval_id
            ),
            None,
        )
        if task is None:
            return _task_error("APPROVAL_NOT_FOUND", "approval is no longer pending")
        approval = dict(task.progress or {})
        expired = int(approval.get("expires_at") or 0) <= int(time.time())
        approved = decision == "approve" and not expired
        request = CheckpointRequest(
            thread_id=str(approval["thread_id"]),
            owner_kind=approval["owner_kind"],
            owner_id=str(approval["owner_id"]),
            retention=approval["retention"],
        )
        try:
            await self.command_inbox.resume_after_approval(task.key)
        except CommandInboxError:
            return _task_error("APPROVAL_NOT_FOUND", "approval is no longer pending")
        try:
            orchestrator = await self.base.get_or_create_orchestrator(sid)
            result = await orchestrator.resume_checkpoint(
                request,
                approval_id=approval_id,
                approved=approved,
            )
            if not approved:
                resolved = await self.command_inbox.cancel(
                    task.key,
                    message="Approval rejected",
                )
            elif result.get("error"):
                resolved = await self.command_inbox.fail(
                    task.key,
                    error_code=str(result["error"]),
                    error_message=str(result["error"]),
                )
            else:
                resolved = await self.command_inbox.succeed(
                    task.key,
                    {
                        "text": str(result.get("response_text") or ""),
                        "approval_id": approval_id,
                        "approved": approved,
                    },
                )
        except Exception as exc:
            resolved = await self.command_inbox.fail(
                task.key,
                error_code=str(getattr(exc, "code", "APPROVAL_RESUME_FAILED")),
                error_message=str(exc),
            )
        payload = {
            **resolved.snapshot(),
            "approval_id": approval_id,
            "decision": "approve" if approved else "reject",
            "reason": "timeout" if expired else None,
        }
        await self.sio.emit(event_name("tool", "approval_resolved"), payload)
        return {"ok": True, "data": payload}

    async def expire_tool_approvals(self) -> int:
        expired = 0
        now = int(time.time())
        for task in await self.command_inbox.waiting_approvals():
            approval = dict(task.progress or {})
            if int(approval.get("expires_at") or 0) > now:
                continue
            response = await self.on_tool_approval_decide(
                str(approval.get("session_id") or "timeout"),
                {
                    "approval_id": str(approval.get("approval_id") or ""),
                    "decision": "reject",
                },
            )
            if response.get("ok") is True:
                expired += 1
        return expired

    # ── Connection events ─────────────────────────────────────────────

    async def on_connect(self, sid: str, environ: dict) -> None:
        await self.lifecycle.on_connect(sid, environ)
        await self.bilibili.emit_current_snapshot(sid)

    async def on_disconnect(self, sid: str) -> None:
        self.chat.cancel_sandbox_tasks_for_sid(sid)
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
        return await self.config_handlers.on_switch_config(sid, data)

    async def on_set_log_level(self, sid: str, data: dict) -> None:
        return await self.config_handlers.on_set_log_level(sid, data)

    async def on_get_config(self, sid: str, data: dict) -> None:
        return await self.config_handlers.on_get_config(sid, data)

    # ── Heartbeat ─────────────────────────────────────────────────────

    async def on_heartbeat(self, sid: str, data: dict) -> None:
        return await self.config_handlers.on_heartbeat(sid, data)

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

    async def on_bilibili_connect(
        self,
        sid: str,
        data: dict | None,
    ) -> dict[str, object]:
        return await self.bilibili.on_bilibili_connect(sid, data)

    async def on_bilibili_disconnect(
        self,
        sid: str,
        data: dict | None = None,
    ) -> dict[str, object]:
        return await self.bilibili.on_bilibili_disconnect(sid, data)

    async def on_bilibili_update_room(
        self,
        sid: str,
        data: dict | None,
    ) -> dict[str, object]:
        return await self.bilibili.on_bilibili_update_room(sid, data)

    # ── Minecraft bot control events ───────────────────────────────────

    async def on_minecraft_connect(self, sid: str, data: dict) -> None:
        return await self.minecraft.on_minecraft_connect(sid, data)

    async def on_minecraft_status(self, sid: str, data: dict) -> None:
        return await self.minecraft.on_minecraft_status(sid, data)

    async def on_minecraft_disconnect(self, sid: str, data: dict) -> None:
        return await self.minecraft.on_minecraft_disconnect(sid, data)

    async def on_minecraft_shutdown(self, sid: str, data: dict) -> None:
        return await self.minecraft.on_minecraft_shutdown(sid, data)

    async def on_minecraft_reattach_viewer(self, sid: str, data: dict) -> None:
        return await self.minecraft.on_minecraft_reattach_viewer(sid, data)

    # ── Persona events ────────────────────────────────────────────────

    async def on_translation_configure(self, sid: str, data: dict) -> None:
        return await self.config_handlers.on_translation_configure(sid, data)

    async def on_get_available_personas(self, sid: str, data: dict) -> dict:
        return await self.persona.on_get_available_personas(sid, data)

    async def on_set_persona(self, sid: str, data: dict) -> dict[str, object]:
        return await self.persona.on_set_persona(sid, data)

    async def on_set_personality_mode(self, sid: str, data: dict) -> None:
        return await self.persona.on_set_personality_mode(sid, data)

    # ── Singing events ────────────────────────────────────────────────

    async def on_sing_process(self, sid: str, data: dict) -> None:
        return await self.singing.on_sing_process(sid, data)

    async def on_sing_confirm_lyrics(self, sid: str, data: dict) -> dict[str, object]:
        return await self.singing.on_sing_confirm_lyrics(sid, data)

    async def on_sing_cancel(self, sid: str, data: dict) -> dict[str, object]:
        return await self.singing.on_sing_cancel(sid, data)

    async def on_sing_subtitle_sync(self, sid: str, data: dict) -> None:
        return await self.singing.on_sing_subtitle_sync(sid, data)

    # ── Memory / Wiki (V2 bridge) ────────────────────────────────────

    async def on_memory_organize(self, sid: str, data: dict) -> dict[str, Any]:
        return await self.memory.on_memory_organize(sid, data)

    async def on_memory_list(self, sid: str, data: dict) -> dict:
        return await self.memory.on_list(sid, data)

    async def on_memory_get(self, sid: str, data: dict) -> dict:
        return await self.memory.on_get(sid, data)

    async def on_memory_search(self, sid: str, data: dict) -> dict:
        return await self.memory.on_search(sid, data)

    async def on_memory_pin(self, sid: str, data: dict) -> dict:
        return await self.memory.on_pin(sid, data)

    async def on_memory_forget(self, sid: str, data: dict) -> dict:
        return await self.memory.on_forget(sid, data)

    async def on_memory_change(self, sid: str, data: dict) -> dict:
        return await self.memory.on_change(sid, data)

    async def on_memory_job(self, sid: str, data: dict) -> dict:
        return await self.memory.on_job(sid, data)

    async def on_get_wiki_pages(self, sid: str, data: dict) -> dict:
        return await self.memory.on_get_wiki_pages(sid, data)

    # ── Meme review events ─────────────────────────────────────────────

    async def on_add_meme(self, sid: str, data: dict) -> dict:
        return await self.meme.on_add_meme(sid, data)

    async def on_list_memes(self, sid: str, data: dict) -> dict:
        return await self.meme.on_list_memes(sid, data)

    async def on_review_meme(self, sid: str, data: dict) -> dict:
        return await self.meme.on_review_meme(sid, data)

    async def on_export_meme_dataset(self, sid: str, data: dict) -> dict:
        return await self.meme.on_export_dataset(sid, data)

    async def on_collect_memes(self, sid: str, data: dict) -> dict:
        return await self.meme.on_collect_memes(sid, data)


def register_routes(
    sio: "AsyncServer",
    session_manager: "SessionManager",
    desktop_manager: DesktopClientManager | None = None,
    live2d_manager: Live2DManager | None = None,
    bilibili_config: dict[str, Any] | None = None,
    observation_recorder: "ObservationRecorder | None" = None,
    observation_query: "ObservationQuery | None" = None,
    observation_report_store: "ObservationReportStore | None" = None,
    command_inbox: CommandInbox | None = None,
    security: SecurityRuntime | None = None,
) -> RouteHandlers:
    """Register all routes to the Socket.IO server."""
    handlers = RouteHandlers(
        sio,
        session_manager,
        desktop_manager,
        live2d_manager,
        observation_recorder,
        observation_query,
        observation_report_store,
        command_inbox,
    )

    handlers.bilibili.configure(bilibili_config)

    security = security or SecurityRuntime.from_effective_config(None)

    # Connection events
    async def connect_adapter(
        sid: str,
        environ: dict[str, Any],
        auth: dict[str, Any] | None = None,
    ) -> bool | None:
        ip = str(environ.get("REMOTE_ADDR") or "unknown")
        try:
            security.check_connection_limit(ip)
        except RateLimitError as exc:
            await security.record_error("RATE_LIMITED", surface="socket_connect")
            raise ConnectionRefusedError(
                {"code": "RATE_LIMITED", "retry_after": exc.retry_after}
            ) from exc
        try:
            principal = await security.authenticate_socket(environ, auth)
        except AuthSessionStoreUnavailableError as exc:
            await security.record_error(
                "AUTH_SESSION_STORE_UNAVAILABLE",
                surface="socket_connect",
            )
            raise ConnectionRefusedError({"code": "AUTH_SESSION_STORE_UNAVAILABLE"}) from exc
        if principal is None:
            await security.record_error("UNAUTHORIZED", surface="socket_connect")
            raise ConnectionRefusedError({"code": "UNAUTHORIZED"})
        security.bind_socket(sid, principal)
        await handlers.on_connect(sid, environ)
        pending = await handlers.on_tool_approval_list(sid)
        for approval in pending["approvals"]:
            await sio.emit(event_name("tool", "approval_required"), approval, to=sid)
        return None

    async def disconnect_adapter(sid: str) -> None:
        security.unbind_socket(sid)
        await handlers.on_disconnect(sid)

    sio.on("connect", connect_adapter)
    sio.on("disconnect", disconnect_adapter)

    # Conversation events
    text_events = (event_name("chat", "text"), *event_aliases("chat", "text"))
    for text_event in text_events:

        async def text_adapter(
            sid: str,
            data: dict,
            _event: str = text_event,
        ) -> dict[str, Any] | None:
            limited = await _chat_rate_error(security, sid)
            if limited is not None:
                return limited
            await handlers.chat.on_text_event(sid, _event, data)
            return None

        sio.on(text_event, text_adapter)
    developer_text_event = event_name("chat", "developer_text")

    async def developer_text_adapter(sid: str, data: dict) -> dict[str, Any] | None:
        limited = await _chat_rate_error(security, sid)
        if limited is not None:
            return limited
        await handlers.chat.on_text_event(
            sid,
            developer_text_event,
            data,
            developer_console=True,
        )
        return None

    def chat_guard(handler: Any) -> Any:
        async def adapter(sid: str, data: dict) -> Any:
            limited = await _chat_rate_error(security, sid)
            return limited if limited is not None else await handler(sid, data)

        return adapter

    def control_guard(handler: Any) -> Any:
        async def adapter(sid: str, data: dict | None = None) -> Any:
            limited = await _control_rate_error(security, sid)
            return limited if limited is not None else await handler(sid, data or {})

        return adapter

    sio.on(developer_text_event, developer_text_adapter)
    sio.on(
        event_name("chat", "sandbox_request"),
        chat_guard(handlers.chat.on_sandbox_request),
    )
    sio.on(
        event_name("chat", "sandbox_cancel"),
        control_guard(handlers.chat.on_sandbox_cancel),
    )
    sio.on(event_name("chat", "audio"), handlers.on_raw_audio_data)
    sio.on(
        event_name("chat", "audio_end"),
        chat_guard(handlers.on_mic_audio_end),
    )
    sio.on(
        event_name("chat", "interrupt"),
        control_guard(handlers.on_interrupt_signal),
    )

    # History events
    sio.on(event_name("history", "list"), handlers.on_fetch_history_list)
    sio.on(event_name("history", "fetch"), handlers.on_fetch_history)
    sio.on(
        event_name("history", "clear"),
        control_guard(handlers.on_clear_history),
    )
    sio.on(
        event_name("history", "create"),
        control_guard(handlers.on_create_new_history),
    )

    # Config events
    sio.on(
        event_name("config", "switch"),
        control_guard(handlers.on_switch_config),
    )
    sio.on(
        event_name("config", "log_level"),
        control_guard(handlers.on_set_log_level),
    )
    sio.on(event_name("config", "get"), handlers.on_get_config)

    # Heartbeat
    sio.on(event_name("system", "heartbeat"), handlers.on_heartbeat)

    # Durable task status
    sio.on(event_name("task", "status"), handlers.on_task_status)

    async def approval_list_adapter(sid: str, data: dict | None = None) -> dict[str, Any]:
        limited = await _control_rate_error(security, sid)
        if limited is not None:
            return limited
        return await handlers.on_tool_approval_list(sid, data)

    async def approval_decide_adapter(sid: str, data: dict) -> dict[str, Any]:
        limited = await _control_rate_error(security, sid)
        if limited is not None:
            return limited
        return await handlers.on_tool_approval_decide(sid, data)

    sio.on(event_name("tool", "approval_list"), approval_list_adapter)
    sio.on(event_name("tool", "approval_decide"), approval_decide_adapter)

    # Desktop client events
    sio.on(event_name("desktop", "register"), handlers.on_desktop_register)
    sio.on(
        event_name("desktop", "live2d_action"),
        control_guard(handlers.on_desktop_live2d_action),
    )
    sio.on(
        event_name("desktop", "chat_message"),
        chat_guard(handlers.on_desktop_chat_message),
    )
    sio.on(
        event_name("desktop", "voice_start"),
        control_guard(handlers.on_desktop_voice_start),
    )
    sio.on(
        event_name("desktop", "voice_stop"),
        control_guard(handlers.on_desktop_voice_stop),
    )

    # Bilibili frontend control events
    sio.on(
        event_name("bilibili", "connect"),
        control_guard(handlers.on_bilibili_connect),
    )
    sio.on(
        event_name("bilibili", "disconnect"),
        control_guard(handlers.on_bilibili_disconnect),
    )
    sio.on(
        event_name("bilibili", "update_room"),
        control_guard(handlers.on_bilibili_update_room),
    )

    # Minecraft bot control events
    sio.on(
        event_name("minecraft", "connect"),
        control_guard(handlers.on_minecraft_connect),
    )
    sio.on(event_name("minecraft", "status"), handlers.on_minecraft_status)
    sio.on(
        event_name("minecraft", "disconnect"),
        control_guard(handlers.on_minecraft_disconnect),
    )
    sio.on(
        event_name("minecraft", "shutdown"),
        control_guard(handlers.on_minecraft_shutdown),
    )
    sio.on(
        event_name("minecraft", "reattach_viewer"),
        control_guard(handlers.on_minecraft_reattach_viewer),
    )

    # Translation configuration events
    sio.on(
        event_name("translation", "configure"),
        control_guard(handlers.on_translation_configure),
    )

    # Persona runtime switching
    sio.on(event_name("persona", "list"), handlers.on_get_available_personas)
    sio.on(
        event_name("persona", "set"),
        control_guard(handlers.on_set_persona),
    )

    # Personality mode runtime switching
    sio.on(
        event_name("persona", "set_mode"),
        control_guard(handlers.on_set_personality_mode),
    )

    # Singing module events
    sio.on(
        event_name("sing", "process"),
        control_guard(handlers.on_sing_process),
    )
    sio.on(
        event_name("sing", "confirm_lyrics"),
        control_guard(handlers.on_sing_confirm_lyrics),
    )
    sio.on(
        event_name("sing", "cancel"),
        control_guard(handlers.on_sing_cancel),
    )
    sio.on(event_name("sing", "subtitle_sync"), handlers.on_sing_subtitle_sync)

    # Memory: wiki pages (legacy compat — delegates to V2)
    sio.on(
        event_name("memory", "organize"),
        control_guard(handlers.on_memory_organize),
    )
    sio.on(event_name("memory", "list"), handlers.on_memory_list)
    sio.on(event_name("memory", "get"), handlers.on_memory_get)
    sio.on(event_name("memory", "search"), handlers.on_memory_search)
    sio.on(
        event_name("memory", "pin"),
        control_guard(handlers.on_memory_pin),
    )
    sio.on(
        event_name("memory", "forget"),
        control_guard(handlers.on_memory_forget),
    )
    sio.on(
        event_name("memory", "change"),
        control_guard(handlers.on_memory_change),
    )
    sio.on(event_name("memory", "job"), handlers.on_memory_job)
    sio.on(event_name("memory", "list_pages"), handlers.on_get_wiki_pages)

    # Meme review
    sio.on(
        event_name("meme", "add"),
        control_guard(handlers.on_add_meme),
    )
    sio.on(event_name("meme", "list"), handlers.on_list_memes)
    sio.on(
        event_name("meme", "review"),
        control_guard(handlers.on_review_meme),
    )
    sio.on(event_name("meme", "dataset"), handlers.on_export_meme_dataset)
    sio.on(
        event_name("meme", "collect"),
        control_guard(handlers.on_collect_memes),
    )

    logger.info("WebSocket routes registered")
    return handlers


def _task_error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


async def _control_rate_error(security: SecurityRuntime, sid: str) -> dict[str, Any] | None:
    rate_owner = security.socket_rate_owner(sid)
    if rate_owner is None:
        await security.record_error("UNAUTHORIZED", surface="socket_control")
        return _task_error("UNAUTHORIZED", "Authentication required")
    try:
        security.check_control_limit(rate_owner)
    except RateLimitError as exc:
        await security.record_error("RATE_LIMITED", surface="socket_control")
        return {
            **_task_error("RATE_LIMITED", "Control rate limit exceeded"),
            "retry_after": exc.retry_after,
        }
    return None


async def _chat_rate_error(security: SecurityRuntime, sid: str) -> dict[str, Any] | None:
    rate_owner = security.socket_rate_owner(sid)
    if rate_owner is None:
        await security.record_error("UNAUTHORIZED", surface="socket_chat")
        return _task_error("UNAUTHORIZED", "Authentication required")
    try:
        security.check_chat_limit(rate_owner)
    except RateLimitError as exc:
        await security.record_error("RATE_LIMITED", surface="socket_chat")
        return {
            **_task_error("RATE_LIMITED", "Chat rate limit exceeded"),
            "retry_after": exc.retry_after,
        }
    return None


def _approval_snapshot(task: Any) -> dict[str, Any]:
    return {
        **dict(task.progress or {}),
        "kind": task.key.kind,
        "task_id": task.key.task_id,
        "status": task.status.value,
        "created_at": task.created_at_ms,
        "updated_at": task.updated_at_ms,
    }
