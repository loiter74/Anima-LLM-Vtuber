"""
Chat/conversation handlers — text input, audio, history management.

Handles user text/audio input, VAD processing, interrupt signals,
and conversation history operations.
"""

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from loguru import logger

from animetta.core.message_filter import is_probe_message
from animetta.memory.v2.context import normalize_actor_id
from animetta.orchestration.chat_contracts import (
    ChatErrorComponent,
    ChatErrorPayload,
    ChatErrorPhase,
    ChatErrorType,
    ChatIdentity,
    ChatTransportMode,
    ChatTurnCommand,
    normalize_chat_command,
)
from animetta.orchestration.chat_delivery import ChatDelivery
from animetta.orchestration.graph.interrupt_handler import get_interrupt_handler
from animetta.services.effects import (
    EffectPlanner,
    create_default_effect_runtime,
)
from animetta.services.meme.styles import get_meme_style, parse_meme_invocation

from ...socket_events import EVENTS, resolve_socket_event

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..session import SessionManager
    from .base_handler import BaseSocketHandler


class ChatHandlers:
    """Chat and conversation event handlers.

    Receives sio, session_manager, and a reference to BaseSocketHandler
    for shared utilities like _get_or_create_orchestrator.
    """

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        admin: "BaseSocketHandler",
    ):
        self.sio = sio
        self.session_manager = session_manager
        self.admin = admin
        self._raw_audio_first_sids: set = set()
        self._conversation_locks: dict[str, asyncio.Lock] = {}

    # ── Text input ────────────────────────────────────────────────────

    @staticmethod
    def _correlation_identity(data: Any) -> ChatIdentity:
        payload = data if isinstance(data, dict) else {}

        def valid_uuid(field: str) -> str | None:
            value = payload.get(field)
            if not isinstance(value, str):
                return None
            try:
                parsed = UUID(value)
            except ValueError:
                return None
            return value if str(parsed) == value else None

        task_id = valid_uuid("task_id") or valid_uuid("turn_id") or str(uuid4())
        return ChatIdentity(
            message_id=valid_uuid("message_id") or str(uuid4()),
            conversation_id=valid_uuid("conversation_id") or str(uuid4()),
            task_id=task_id,
            turn_id=task_id,
        )

    async def _emit_command_error(
        self,
        sid: str,
        identity: ChatIdentity,
        *,
        error_type: ChatErrorType,
        message: str,
        component: ChatErrorComponent,
        phase: ChatErrorPhase,
        transport_mode: ChatTransportMode = ChatTransportMode.CANONICAL,
    ) -> None:
        safe_message = (message.strip() or error_type.value)[:512]
        payload = ChatErrorPayload(
            message_id=identity.message_id,
            conversation_id=identity.conversation_id,
            task_id=identity.task_id,
            turn_id=identity.turn_id,
            type=error_type,
            message=safe_message,
            component=component,
            phase=phase,
            retryable=False,
            terminal=True,
        )
        delivery = ChatDelivery(self.sio, identity, transport_mode)
        await delivery.emit(
            "system",
            "error",
            payload.model_dump(
                mode="json",
                exclude={"message_id", "conversation_id", "task_id", "turn_id"},
            ),
            to=sid,
        )

    async def on_text_event(self, sid: str, event: str, data: dict) -> None:
        """Filter and normalize one canonical or catalog-declared text event."""
        if is_probe_message(data):
            logger.debug("[{}] Dropping inspection/health probe before normalization", sid)
            return
        try:
            command = normalize_chat_command(event, data)
        except (TypeError, ValueError) as exc:
            try:
                transport_mode = (
                    ChatTransportMode.LEGACY
                    if resolve_socket_event(event).is_legacy
                    else ChatTransportMode.CANONICAL
                )
            except KeyError:
                transport_mode = ChatTransportMode.CANONICAL
            await self._emit_command_error(
                sid,
                self._correlation_identity(data),
                error_type=ChatErrorType.VALIDATION,
                message=str(exc),
                component=ChatErrorComponent.TRANSPORT,
                phase=ChatErrorPhase.VALIDATION,
                transport_mode=transport_mode,
            )
            return
        await self.on_text_command(sid, command)

    async def on_text_command(self, sid: str, command: ChatTurnCommand) -> None:
        """Serialize and dispatch one transport-normalized text command."""
        lock = self._conversation_locks.setdefault(
            command.conversation_id,
            asyncio.Lock(),
        )
        async with lock:
            await self._process_text_command(sid, command)

    async def _process_text_command(self, sid: str, command: ChatTurnCommand) -> None:
        text = command.text
        logger.info("[{}] Received normalized text input: {}", sid, text)
        delivery = ChatDelivery(self.sio, command, command.transport_mode)

        if await self._handle_explicit_meme_invocation(sid, text, delivery):
            return

        try:
            orchestrator = await self.admin._get_or_create_orchestrator(sid)
            channel = (
                "bilibili" if command.is_acceptance and command.source == "livestream" else "local"
            )
            actor_id = normalize_actor_id(command.user_id or "user", channel)
            result = await orchestrator.process_text(
                text=text,
                user_id=actor_id,
                user_name=command.from_name or "User",
                channel_id=sid,
                message_id=command.message_id,
                conversation_id=command.conversation_id,
                task_id=command.task_id,
                turn_id=command.task_id,
                transport_mode=command.transport_mode.value,
                channel=channel,
            )
            if isinstance(result, dict) and result.get("error"):
                await self._emit_command_error(
                    sid,
                    command,
                    error_type=ChatErrorType.PROCESSING,
                    message=str(result["error"]),
                    component=ChatErrorComponent.WORKFLOW,
                    phase=ChatErrorPhase.WORKFLOW,
                    transport_mode=command.transport_mode,
                )
        except Exception as exc:
            await self._emit_command_error(
                sid,
                command,
                error_type=ChatErrorType.INTERNAL,
                message=str(exc),
                component=ChatErrorComponent.WORKFLOW,
                phase=ChatErrorPhase.WORKFLOW,
                transport_mode=command.transport_mode,
            )

    async def on_text_input(self, sid: str, data: dict) -> None:
        """Compatibility facade for internal callers that predate named routes."""
        if is_probe_message(data):
            return
        command = normalize_chat_command("text_input", data).model_copy(
            update={"transport_mode": ChatTransportMode.CANONICAL}
        )
        await self.on_text_command(sid, command)

    async def _handle_explicit_meme_invocation(
        self,
        sid: str,
        text: str,
        delivery: ChatDelivery,
    ) -> bool:
        invocation = parse_meme_invocation(text)
        if invocation is None:
            return False

        style = get_meme_style(invocation.style_id)
        if style is None:
            await self._emit_command_error(
                sid,
                delivery.identity,
                error_type=ChatErrorType.VALIDATION,
                message=f"Unknown meme style: {invocation.style_id}",
                component=ChatErrorComponent.WORKFLOW,
                phase=ChatErrorPhase.WORKFLOW,
                transport_mode=delivery.transport_mode,
            )
            return True

        runtime = create_default_effect_runtime()
        response_plan = EffectPlanner().plan(user_text=text)
        response = await runtime.run(response_plan)
        if not response.effects or not response.effects[0].success:
            message = (
                response.effects[0].error
                if response.effects and response.effects[0].error
                else f"Unsupported meme style: {style.id}"
            )
            await self._emit_command_error(
                sid,
                delivery.identity,
                error_type=ChatErrorType.PROCESSING,
                message=message,
                component=ChatErrorComponent.WORKFLOW,
                phase=ChatErrorPhase.WORKFLOW,
                transport_mode=delivery.transport_mode,
            )
            return True

        await delivery.emit("chat", "control", {"signal": "conversation-start"}, to=sid)
        await delivery.emit(
            "chat",
            "sentence",
            {
                "text": response.text,
                "seq": 0,
                "lang": "zh",
                "metadata": response.to_metadata(),
            },
            to=sid,
        )
        await delivery.emit(
            "chat",
            "sentence",
            {"text": "", "seq": 1, "lang": "zh", "is_complete": True},
            to=sid,
        )
        await delivery.emit("chat", "control", {"signal": "conversation-end"}, to=sid)
        return True

    # ── Audio / VAD ───────────────────────────────────────────────────

    async def on_raw_audio_data(self, sid: str, data: dict) -> None:
        """Handle raw audio data for VAD detection."""
        audio_chunk = data.get("audio", [])

        if not audio_chunk:
            logger.debug(f"[{sid}] Received empty audio data")
            return

        if sid not in self._raw_audio_first_sids:
            self._raw_audio_first_sids.add(sid)
            logger.info(f"[{sid}] [RAW_AUDIO] Starting to receive audio data")

        try:
            await self.admin._get_or_create_orchestrator(sid)

            processor = self.session_manager.get_audio_processor(sid)
            if processor:
                await processor.process_chunk(audio_chunk)
            else:
                logger.error(f"[{sid}] Audio processor not created")

        except Exception as e:
            logger.error(f"[{sid}] VAD processing error: {e}", exc_info=True)

    async def on_mic_audio_end(self, sid: str, data: dict) -> None:
        """Audio input end event."""
        logger.info(f"[{sid}] Audio input ended")

        try:
            processor = self.session_manager.get_audio_processor(sid)
            if processor:
                await processor.process_end()

        except Exception as e:
            logger.error(f"[{sid}] Error processing audio: {e}")
            await self._emit_command_error(
                sid,
                self._correlation_identity(data),
                error_type=ChatErrorType.PROCESSING,
                message=str(e),
                component=ChatErrorComponent.WORKFLOW,
                phase=ChatErrorPhase.WORKFLOW,
            )

    # ── Interrupt ─────────────────────────────────────────────────────

    async def on_interrupt_signal(self, sid: str, data: dict) -> None:
        """Interrupt signal - stop LLM generation and audio playback."""
        heard_response = data.get("text", "")
        logger.info(
            f"[{sid}] Received interrupt signal, "
            f"heard response: {heard_response[:50] if heard_response else '(empty)'}..."
        )

        interrupt_handler = get_interrupt_handler()
        interrupt_handler.set_interrupt(sid)

        identity = self._correlation_identity(data)
        delivery = ChatDelivery(self.sio, identity, ChatTransportMode.CANONICAL)
        await delivery.emit("chat", "stop_audio", {}, to=sid)
        await delivery.emit("chat", "control", {"type": "control", "text": "interrupted"}, to=sid)

    # ── History ────────────────────────────────────────────────────────

    async def on_fetch_history_list(self, sid: str, data: dict) -> None:
        """Fetch chat history list."""
        logger.info(f"[{sid}] Requested chat history list")

    async def on_fetch_history(self, sid: str, data: dict) -> None:
        """Fetch specific history record."""
        history_uid = data.get("history_uid")
        logger.info(f"[{sid}] Requested history: {history_uid}")
        messages: list[dict[str, Any]] = []

        await self.sio.emit(
            EVENTS["history"]["list"]["name"],
            {"type": EVENTS["history"]["list"]["name"], "messages": messages},
            to=sid,
        )

    async def on_clear_history(self, sid: str, data: dict) -> None:
        """Clear conversation history."""
        logger.info(f"[{sid}] Clearing conversation history")

        ctx = self.session_manager.get_context(sid)
        if ctx and ctx.llm_engine:
            ctx.llm_engine.clear_history()
            logger.info(f"[{sid}] Conversation history cleared")

            await self.sio.emit(
                EVENTS["history"]["clear"]["name"],
                {"type": EVENTS["history"]["clear"]["name"]},
                to=sid,
            )

    async def on_create_new_history(self, sid: str, data: dict) -> None:
        """Create new conversation history."""
        logger.info(f"[{sid}] Creating new conversation history")

        await self.sio.emit(
            EVENTS["history"]["create"]["name"],
            {"type": EVENTS["history"]["create"]["name"], "history_uid": "new_history_001"},
            to=sid,
        )
