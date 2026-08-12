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
from animetta.core.readiness import resolve_service_identity
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
from animetta.services.dialogue import (
    SandboxConversationError,
    SandboxConversationService,
    SandboxTurn,
)
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
        self._sandbox_tasks: dict[str, asyncio.Task[None]] = {}
        self._sandbox_task_sids: dict[str, str] = {}

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

    async def on_text_event(
        self,
        sid: str,
        event: str,
        data: dict,
        *,
        developer_console: bool = False,
    ) -> None:
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
        await self.on_text_command(sid, command, developer_console=developer_console)

    async def on_text_command(
        self,
        sid: str,
        command: ChatTurnCommand,
        *,
        developer_console: bool = False,
    ) -> None:
        """Serialize and dispatch one transport-normalized text command."""
        lock = self._conversation_locks.setdefault(
            command.conversation_id,
            asyncio.Lock(),
        )
        async with lock:
            await self._process_text_command(
                sid,
                command,
                developer_console=developer_console,
            )

    async def _process_text_command(
        self,
        sid: str,
        command: ChatTurnCommand,
        *,
        developer_console: bool = False,
    ) -> None:
        text = command.text
        logger.info("[{}] Received normalized text input: {}", sid, text)
        delivery = ChatDelivery(self.sio, command, command.transport_mode)

        if not developer_console and await self._handle_explicit_meme_invocation(
            sid, text, delivery
        ):
            return

        try:
            orchestrator = await self.admin._get_or_create_orchestrator(sid)
            channel = (
                "developer_console"
                if developer_console
                else "bilibili"
                if command.is_acceptance and command.source == "livestream"
                else "local"
            )
            actor_id = normalize_actor_id(
                "developer" if developer_console else command.user_id or "user",
                channel,
            )
            trusted_metadata: dict[str, Any] = (
                {
                    "actor_role": "developer",
                    "source": "developer_console",
                    "live_session_id": self.admin.live_session_id,
                    "stream_id": self.admin.live_session_id,
                    "audience": "livestream",
                }
                if developer_console
                else {}
            )
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
                **trusted_metadata,
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

    async def on_sandbox_request(self, sid: str, data: dict) -> None:
        """Run a private LLM conversation without graph, TTS, subtitle, or memory effects."""
        try:
            identity = self._sandbox_identity(data)
        except ValueError:
            await self._emit_sandbox_chunk(
                sid,
                self._correlation_identity(data),
                seq=0,
                provider="unavailable",
                is_complete=True,
                error_code="validation_error",
            )
            return
        text = data.get("text") if isinstance(data, dict) else None
        history_data = data.get("history", []) if isinstance(data, dict) else []
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > 4000
            or not isinstance(history_data, list)
        ):
            await self._emit_sandbox_chunk(
                sid,
                identity,
                seq=0,
                provider="unavailable",
                is_complete=True,
                error_code="validation_error",
            )
            return
        try:
            history = self._sandbox_history(history_data)
        except ValueError:
            await self._emit_sandbox_chunk(
                sid,
                identity,
                seq=0,
                provider="unavailable",
                is_complete=True,
                error_code="validation_error",
            )
            return

        prior = self._sandbox_tasks.get(identity.task_id)
        if prior:
            await self._emit_sandbox_chunk(
                sid,
                identity,
                seq=0,
                provider="unavailable",
                is_complete=True,
                error_code="task_conflict",
            )
            return
        task = asyncio.create_task(self._run_sandbox(sid, identity, text.strip(), history))
        self._sandbox_tasks[identity.task_id] = task
        self._sandbox_task_sids[identity.task_id] = sid
        task.add_done_callback(
            lambda completed: self._discard_sandbox_task(identity.task_id, completed)
        )

    async def on_sandbox_cancel(self, sid: str, data: dict) -> None:
        try:
            identity = self._sandbox_identity(data)
        except ValueError:
            return
        task = self._sandbox_tasks.get(identity.task_id)
        if task and self._sandbox_task_sids.get(identity.task_id) == sid:
            task.cancel()

    @staticmethod
    def _sandbox_identity(data: Any) -> ChatIdentity:
        if not isinstance(data, dict):
            raise ValueError("sandbox payload must be an object")
        return ChatIdentity.model_validate(
            {
                field: data.get(field)
                for field in ("message_id", "conversation_id", "task_id", "turn_id")
            }
        )

    def cancel_sandbox_tasks_for_sid(self, sid: str) -> None:
        """Cancel private model work owned by one disconnected client."""
        for task_id, owner_sid in list(self._sandbox_task_sids.items()):
            if owner_sid == sid:
                task = self._sandbox_tasks.get(task_id)
                if task:
                    task.cancel()

    def _discard_sandbox_task(self, task_id: str, completed: asyncio.Task[None]) -> None:
        if self._sandbox_tasks.get(task_id) is completed:
            self._sandbox_tasks.pop(task_id, None)
            self._sandbox_task_sids.pop(task_id, None)

    @staticmethod
    def _sandbox_history(data: list[Any]) -> list[SandboxTurn]:
        history: list[SandboxTurn] = []
        for item in data[-20:]:
            if not isinstance(item, dict):
                raise ValueError("history item must be an object")
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                raise ValueError("invalid history item")
            clean = content.strip()
            if not clean or len(clean) > 4000:
                raise ValueError("invalid history content")
            history.append(SandboxTurn(role=role, content=clean))
        return history

    async def _run_sandbox(
        self,
        sid: str,
        identity: ChatIdentity,
        text: str,
        history: list[SandboxTurn],
    ) -> None:
        config = self.admin.get_active_config()
        configured_provider = config.providers["llm"]
        provider_name = "unavailable"
        model_name: str | None = None
        seq = 0
        try:
            context = await self.admin.get_or_create_context(sid)
            if context.llm_engine is None:
                raise SandboxConversationError("llm_unavailable")
            resolved = resolve_service_identity(
                "llm",
                context.llm_engine,
                configured_provider,
            )
            if resolved is None:
                raise SandboxConversationError("identity_unavailable")
            provider_name = str(resolved.get("provider") or resolved.get("type") or "unavailable")
            model_name = resolved.get("model")
            if "mock" in {provider_name, str(resolved.get("type") or "")}:
                raise SandboxConversationError("mock_disallowed")
            service = SandboxConversationService(context.llm_engine)
            async for chunk in service.stream(
                text,
                history,
                system_prompt=config.get_system_prompt(),
            ):
                await self._emit_sandbox_chunk(
                    sid,
                    identity,
                    text=chunk,
                    seq=seq,
                    provider=provider_name,
                    model=model_name,
                )
                seq += 1
            await self._emit_sandbox_chunk(
                sid,
                identity,
                seq=seq,
                provider=provider_name,
                model=model_name,
                is_complete=True,
            )
        except asyncio.CancelledError:
            await self._emit_sandbox_chunk(
                sid,
                identity,
                seq=seq,
                provider=provider_name,
                model=model_name,
                is_complete=True,
                error_code="interrupted",
            )
        except SandboxConversationError as exc:
            await self._emit_sandbox_chunk(
                sid,
                identity,
                seq=seq,
                provider=provider_name,
                model=model_name,
                is_complete=True,
                error_code=exc.code,
            )
        except Exception:
            logger.exception("[{}] Private sandbox failed", sid)
            await self._emit_sandbox_chunk(
                sid,
                identity,
                seq=seq,
                provider=provider_name,
                model=model_name,
                is_complete=True,
                error_code="internal_error",
            )

    async def _emit_sandbox_chunk(
        self,
        sid: str,
        identity: ChatIdentity,
        *,
        seq: int,
        provider: str,
        text: str = "",
        model: str | None = None,
        is_complete: bool = False,
        error_code: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            **identity.model_dump(mode="json"),
            "text": text,
            "seq": seq,
            "provider": provider,
            "is_complete": is_complete,
        }
        if model:
            payload["model"] = model
        if error_code:
            payload["error_code"] = error_code
        await self.sio.emit(EVENTS["chat"]["sandbox_chunk"]["name"], payload, to=sid)

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
