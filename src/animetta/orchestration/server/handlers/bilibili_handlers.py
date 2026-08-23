"""Thin Socket.IO adapter for the process-owned Bilibili session."""

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from loguru import logger

from animetta.checkpointing import CheckpointRequest
from animetta.config import ProactiveTopicsConfig, ReplyPolicyConfig, SceneAnalysisConfig
from animetta.memory.v2.context import normalize_actor_id
from animetta.orchestration.chat_contracts import ChatIdentity
from animetta.orchestration.chat_delivery import ChatDelivery
from animetta.services.bilibili import (
    PROACTIVE_TOPIC_SOURCE,
    DanmakuBuffer,
    DanmakuMessage,
    DanmakuReplyRuntime,
    LivestreamEvent,
    LivestreamSession,
    ProactiveTopicRuntime,
    ReplyCandidate,
    ReplyMetrics,
    TopicSeed,
)
from animetta.services.bilibili.livestream_session import StaleGenerationError
from animetta.services.bilibili.reply_media import bind_reply_media_turn
from animetta.services.scene_analysis import SceneModelGateway, SceneRuntime

from ...chat_contracts import ChatTransportMode
from ...socket_events import EVENTS

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..session import SessionManager
    from .base_handler import BaseSocketHandler


class BilibiliHandlers:
    """Bilibili danmaku service handlers.

    Receives sio, session_manager, and a reference to BaseSocketHandler
    for shared utilities like _get_or_create_orchestrator.
    """

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        admin: "BaseSocketHandler",
        *,
        session: LivestreamSession | None = None,
        sessdata: str = "",
        reply_policy: ReplyPolicyConfig | None = None,
        buffer: DanmakuBuffer | None = None,
        gateway_factory: Any | None = None,
        scene_runtime: SceneRuntime | Any | None = None,
    ) -> None:
        self.sio = sio
        self.session_manager = session_manager
        self.admin = admin

        self._sessdata = sessdata
        self._configured_enabled = False
        self._configured_room_id = 0
        self._reply_policy = reply_policy or ReplyPolicyConfig()
        self._scene_config = SceneAnalysisConfig()
        self._buffer = buffer or DanmakuBuffer()
        if session is None:
            if scene_runtime is None:
                scene_runtime = SceneRuntime(
                    session_id="bilibili-livestream",
                    room_id=1,
                    generation_id=0,
                    mode="shadow",
                )
            reply_runtime = DanmakuReplyRuntime(
                self._reply_policy,
                self._process_reply_candidate,
            )
            session_kwargs: dict[str, Any] = {}
            if gateway_factory is not None:
                session_kwargs["gateway_factory"] = gateway_factory
            session = LivestreamSession(
                status_sink=self.emit_status_snapshot,
                raw_event_sink=self._broadcast_live_event,
                raw_message_sink=self._broadcast_raw_danmaku,
                reply_runtime=reply_runtime,
                scene_runtime=scene_runtime,
                buffer=self._buffer,
                **session_kwargs,
            )
        self.session = session
        self.scene_runtime = scene_runtime
        if self.scene_runtime is not None:
            configure_runtime = getattr(self.scene_runtime, "configure", None)
            if callable(configure_runtime):
                configure_runtime(self._scene_config)
        self._proactive_config = ProactiveTopicsConfig()
        self._proactive_topics = ProactiveTopicRuntime(
            self._proactive_config,
            self._process_proactive_topic,
            self._interrupt_proactive_audio,
            scene_snapshot=self._scene_snapshot,
            busy=lambda: bool(getattr(self.session, "reply_busy", False)),
        )

        # Deprecated compatibility attributes. Lifecycle ownership lives in session.
        self._bilibili_service = None
        self._main_loop: asyncio.AbstractEventLoop | None = None

    @property
    def metrics(self) -> ReplyMetrics:
        """Expose counters owned by the process-wide livestream session."""
        return self.session.metrics

    # ── Session lifecycle ─────────────────────────────────────────────

    def configure(self, config: dict[str, Any] | None) -> None:
        """Apply server-owned Bilibili settings without exposing credentials."""
        values = config or {}
        self._configured_enabled = bool(values.get("enabled", False))
        self._configured_room_id = int(values.get("room_id", 0) or 0)
        self._sessdata = str(values.get("sessdata", "") or "")
        policy_values = values.get("reply_policy", {})
        if isinstance(policy_values, ReplyPolicyConfig):
            self._reply_policy = policy_values
        elif isinstance(policy_values, dict):
            self._reply_policy = ReplyPolicyConfig.model_validate(policy_values)
        self.session.configure_reply_policy(self._reply_policy)

    def configure_scene_analysis(self, config: SceneAnalysisConfig) -> None:
        """Apply application-owned scene settings before room startup."""
        self._scene_config = config
        if self.scene_runtime is not None:
            configure_runtime = getattr(self.scene_runtime, "configure", None)
            if callable(configure_runtime):
                configure_runtime(config)

    def configure_proactive_topics(self, config: ProactiveTopicsConfig) -> None:
        """Apply the application-owned proactive topic controls."""
        self._proactive_config = config
        self._proactive_topics.configure(config)

    async def start_configured(self) -> dict[str, Any]:
        """Start the configured room during the ASGI lifespan."""
        if not self._configured_enabled or self._configured_room_id <= 0:
            return self.session.snapshot()
        return await self.start_bilibili(self._configured_room_id)

    async def start_bilibili(
        self,
        room_id: int,
        sessdata: str | None = None,
        *,
        expected_generation_id: int | None = None,
    ) -> dict[str, Any]:
        """Delegate an atomic room command to the single session owner."""
        await self._prepare_scene_runtime()
        return await self.session.set_room(
            room_id,
            sessdata=self._sessdata if sessdata is None else sessdata,
            expected_generation_id=expected_generation_id,
        )

    async def stop_bilibili(
        self,
        *,
        expected_generation_id: int | None = None,
    ) -> dict[str, Any]:
        """Stop the shared session and cancel pending AI reply work."""
        snapshot = await self.session.stop(expected_generation_id=expected_generation_id)
        await self._proactive_topics.update_status(snapshot)
        return snapshot

    # ── Status broadcast ──────────────────────────────────────────────

    async def emit_status_snapshot(self, payload: dict[str, object]) -> None:
        """Broadcast one authoritative session snapshot to all clients."""
        await self._proactive_topics.update_status(payload)
        await self.sio.emit(
            EVENTS["bilibili"]["danmaku_status"]["name"],
            payload,
        )

    async def emit_current_snapshot(self, sid: str) -> None:
        """Send the current session truth to a newly connected client."""
        await self.sio.emit(
            EVENTS["bilibili"]["danmaku_status"]["name"],
            self.session.snapshot(),
            to=sid,
        )

    # ── Danmaku processing ────────────────────────────────────────────

    async def _broadcast_raw_danmaku(
        self,
        msg: DanmakuMessage,
        _room_id: int,
    ) -> None:
        """Broadcast every raw message independently of AI admission."""
        await self._proactive_topics.notify_activity()
        await self.sio.emit(EVENTS["bilibili"]["danmaku"]["name"], msg.to_dict())

    async def _broadcast_live_event(
        self,
        event: LivestreamEvent,
        room_id: int,
        generation_id: int,
    ) -> None:
        """Broadcast the complete normalized event with its session identity."""
        await self.sio.emit(
            EVENTS["bilibili"]["live_event"]["name"],
            {
                "room_id": room_id,
                "generation_id": generation_id,
                **event.to_dict(),
            },
        )

    async def _process_reply_candidate(self, candidate: ReplyCandidate) -> None:
        with bind_reply_media_turn(candidate.media_turn):
            await self._process_ai_reply(
                candidate.message,
                candidate.room_id,
                reply_id=candidate.reply_id,
            )
        if candidate.media_turn is not None:
            await candidate.media_turn.finish()
        await self._proactive_topics.reset_after_viewer_reply()

    def _scene_snapshot(self):
        if self.scene_runtime is None:
            return None
        snapshot = getattr(self.scene_runtime, "snapshot", None)
        return snapshot() if callable(snapshot) else None

    async def _process_proactive_topic(
        self,
        seed: TopicSeed,
        task_id: str,
        room_id: int,
        generation_id: int,
        recent_outputs: tuple[str, ...],
    ) -> str:
        """Generate one host-only turn through the canonical chat and TTS path."""
        if not self._is_current_live_identity(room_id, generation_id):
            raise StaleGenerationError("livestream generation changed")
        orchestrator = await self.admin._get_or_create_orchestrator("bilibili")
        result = await orchestrator.process_text(
            text="生成本轮直播主动话题。",
            user_id="bilibili:host",
            channel_id="bilibili",
            source=PROACTIVE_TOPIC_SOURCE,
            message_id=task_id,
            conversation_id=task_id,
            task_id=task_id,
            turn_id=task_id,
            transport_mode=ChatTransportMode.CANONICAL.value,
            channel="bilibili",
            stream_id=f"bilibili:{room_id}",
            live_session_id=self.admin.live_session_id,
            actor_role="host",
            audience="livestream",
            reply_id=task_id,
            received_at=time.time(),
            proactive_topic_seed={
                "kind": seed.kind,
                "subject": seed.subject,
                "provenance": seed.provenance,
            },
            proactive_recent_outputs=list(recent_outputs),
            proactive_topic_max_chars=self._proactive_config.max_chars,
            proactive_generation_id=generation_id,
        )
        response = str(result.get("response_text") or "").strip()
        if result.get("error") or not response:
            raise RuntimeError(str(result.get("error") or "empty proactive topic"))
        if not self._is_current_live_identity(room_id, generation_id):
            await self._interrupt_proactive_audio(task_id)
            raise StaleGenerationError("livestream generation changed")
        if self.scene_runtime is not None:
            try:
                await self.scene_runtime.record_host_reply(response)
            except Exception as exc:
                logger.warning(
                    "Proactive scene feedback failed: error_type={}",
                    type(exc).__name__,
                )
        return response

    async def _interrupt_proactive_audio(self, task_id: str) -> None:
        """Stop only the correlated proactive task on public live clients."""
        identity = ChatIdentity(
            message_id=task_id,
            conversation_id=task_id,
            task_id=task_id,
            turn_id=task_id,
        )
        await ChatDelivery(
            self.sio,
            identity,
            ChatTransportMode.CANONICAL,
        ).emit("chat", "stop_audio", {}, to=None)

    def _is_current_live_identity(self, room_id: int, generation_id: int) -> bool:
        snapshot = self.session.snapshot()
        return bool(
            snapshot.get("state") == "live"
            and snapshot.get("generation_id") == generation_id
            and (snapshot.get("room_id") or snapshot.get("desired_room_id")) == room_id
        )

    async def _prepare_scene_runtime(self) -> None:
        """Bind the selected profile LLM before room events can trigger reflection."""
        if self.scene_runtime is None or self._scene_config.mode == "off":
            return
        try:
            service_context = await self.admin.get_or_create_context("bilibili")
            self._bind_scene_context(service_context)
        except Exception as exc:
            logger.warning(
                "Scene runtime preparation failed: error_type={}",
                type(exc).__name__,
            )

    def _bind_scene_context(self, service_context: object) -> None:
        """Apply current scene controls and reuse the context's shared LLM engine."""
        effective_config = getattr(service_context, "config", None)
        scene_config = getattr(effective_config, "scene_analysis", None)
        if isinstance(scene_config, SceneAnalysisConfig):
            self.configure_scene_analysis(scene_config)
        llm = getattr(service_context, "llm_engine", None)
        if llm is not None and self.scene_runtime is not None:
            self.scene_runtime.bind_gateway(
                SceneModelGateway(
                    llm,
                    timeout_seconds=self._scene_config.model_timeout_seconds,
                    max_tokens=self._scene_config.model_max_tokens,
                )
            )

    async def _process_danmaku(self, msg: DanmakuMessage) -> None:
        """Backward-compatible direct processing helper used by focused tests."""
        snapshot = self.session.snapshot()
        room_id = int(snapshot.get("room_id") or snapshot.get("desired_room_id") or 0)
        await self._broadcast_raw_danmaku(msg, room_id)
        await self._process_ai_reply(msg, room_id)

    async def process_program_danmaku(
        self,
        text: str,
        context: dict[str, Any],
        *,
        room_id: int,
    ) -> dict[str, Any]:
        """Inject one controlled test-viewer message through the real reply path."""
        message = DanmakuMessage(
            text=text,
            user_name=str(context.get("display_name") or "首播测试观众"),
            user_id=0,
            meta={"program_run_id": context.get("program_run_id")},
        )
        await self._broadcast_raw_danmaku(message, room_id)
        return await self._process_ai_reply(message, room_id, program_context=context)

    async def _process_ai_reply(
        self,
        msg: DanmakuMessage,
        room_id: int,
        *,
        program_context: dict[str, Any] | None = None,
        reply_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate and deliver one already-admitted AI reply."""
        try:
            task_id = str((program_context or {}).get("turn_id") or reply_id or uuid4())
            source_message_id = getattr(msg, "source_message_id", str(uuid4()))
            message_id = source_message_id
            conversation_id = str(uuid4())
            orchestrator = await self.admin._get_or_create_orchestrator("bilibili")
            scene_metadata: dict[str, object] = {}
            scripted_guidance = (program_context or {}).get("scene_guidance")
            if isinstance(scripted_guidance, dict):
                scene_metadata["scene_guidance"] = scripted_guidance
            elif self.scene_runtime is not None:
                try:
                    service_context = getattr(orchestrator, "service_context", None)
                    if service_context is not None:
                        self._bind_scene_context(service_context)
                    guidance = await self.scene_runtime.guidance_for_reply()
                    if guidance is not None:
                        scene_metadata["scene_guidance"] = guidance.model_dump(mode="json")
                except Exception as exc:
                    logger.warning(
                        "Scene guidance lookup failed: error_type={}",
                        type(exc).__name__,
                    )
            actor_override = (program_context or {}).get("actor_id")
            actor_id = (
                str(actor_override)
                if isinstance(actor_override, str) and actor_override
                else normalize_actor_id(msg.user_id, "bilibili")
            )
            stream_id = f"bilibili:{room_id}" if room_id else None
            checkpoint_request = (program_context or {}).get("checkpoint_request")
            if not isinstance(checkpoint_request, CheckpointRequest):
                checkpoint_request = None
            program_metadata = {
                key: value
                for key, value in (program_context or {}).items()
                if key
                in {
                    "program_run_id",
                    "program_beat_id",
                    "is_probe",
                    "memory_mode",
                }
            }
            result = await orchestrator.process_text(
                text=f"{msg.user_name}说: {msg.text}",
                user_id=actor_id,
                user_name=msg.user_name,
                channel_id="bilibili",
                source=EVENTS["bilibili"]["danmaku"]["name"],
                message_id=message_id,
                conversation_id=conversation_id,
                task_id=task_id,
                turn_id=task_id,
                checkpoint_request=checkpoint_request,
                transport_mode=ChatTransportMode.CANONICAL.value,
                channel="bilibili",
                stream_id=stream_id,
                live_session_id=self.admin.live_session_id,
                actor_role="viewer",
                audience="livestream",
                source_message_id=source_message_id,
                reply_id=task_id,
                received_at=float(getattr(msg, "timestamp", time.time())),
                **cast(dict[str, Any], scene_metadata),
                **program_metadata,
            )

            reply_text = result.get("response_text", "")
            if not reply_text:
                raise RuntimeError(str(result.get("error") or "empty bilibili reply"))

            # Also emit danmaku.ai_reply for the chat message integration
            if reply_text:
                character_name = "AI"
                service_context = getattr(orchestrator, "service_context", None)
                config = getattr(service_context, "config", None)
                if config is None:
                    legacy_core = getattr(service_context, "core", None)
                    config = getattr(legacy_core, "config", None)
                persona = config.get_persona() if config else None
                if persona:
                    character_name = persona.name

                await self.sio.emit(
                    EVENTS["bilibili"]["danmaku_ai_reply"]["name"],
                    {
                        "danmaku_text": msg.text,
                        "reply_text": reply_text,
                        "user_name": msg.user_name,
                        "character_name": character_name,
                        "timestamp": time.time(),
                        "source_message_id": source_message_id,
                        "reply_id": task_id,
                    },
                )
            if reply_text and self.scene_runtime is not None and program_context is None:
                try:
                    await self.scene_runtime.record_host_reply(reply_text)
                except Exception as exc:
                    logger.warning(
                        "Scene host-reply feedback failed: error_type={}",
                        type(exc).__name__,
                    )
            return result
        except Exception as exc:
            logger.error(
                "Bilibili reply processing failed: error_type={}",
                type(exc).__name__,
            )
            raise

    # ── Frontend-initiated Bilibili control ───────────────────────────

    async def on_bilibili_connect(
        self,
        sid: str,
        data: dict[str, object] | None,
    ) -> dict[str, object]:
        """Validate and acknowledge a room command without claiming connection."""
        return await self._handle_room_command(data, action="connect")

    async def on_bilibili_disconnect(
        self,
        sid: str,
        data: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Disconnect safely even when Socket.IO supplies no payload."""
        del sid
        try:
            expected_generation_id = self._parse_expected_generation_id(data)
        except ValueError:
            return self._command_ack(
                accepted=False,
                error_code="invalid_generation_id",
                message="Invalid generation ID",
            )
        logger.info("[Bilibili] Frontend requested disconnect")
        try:
            snapshot = await self.stop_bilibili(
                expected_generation_id=expected_generation_id,
            )
        except StaleGenerationError:
            return self._command_ack(
                accepted=False,
                error_code="stale_generation",
                message="Session generation changed",
            )
        except Exception as exc:
            logger.warning(
                "Bilibili disconnect command failed: error_type={}",
                type(exc).__name__,
            )
            return self._command_ack(
                accepted=False,
                error_code="disconnect_failed",
                message="Disconnect command failed",
            )
        return self._command_ack(
            accepted=True,
            snapshot=snapshot,
            message="Command accepted",
        )

    async def on_bilibili_update_room(
        self,
        sid: str,
        data: dict[str, object] | None,
    ) -> dict[str, object]:
        """Atomically replace the active room through the shared session."""
        del sid
        return await self._handle_room_command(data, action="update_room")

    async def _handle_room_command(
        self,
        data: dict[str, object] | None,
        *,
        action: str,
    ) -> dict[str, object]:
        room_id = data.get("room_id") if isinstance(data, dict) else None
        if not isinstance(room_id, int) or isinstance(room_id, bool) or room_id <= 0:
            return self._command_ack(
                accepted=False,
                error_code="invalid_room_id",
                message="Invalid room ID",
            )

        try:
            expected_generation_id = self._parse_expected_generation_id(data)
        except ValueError:
            return self._command_ack(
                accepted=False,
                error_code="invalid_generation_id",
                message="Invalid generation ID",
            )

        logger.info("[Bilibili] {} requested for room {}", action, room_id)
        try:
            snapshot = await self.start_bilibili(
                room_id,
                expected_generation_id=expected_generation_id,
            )
        except StaleGenerationError:
            return self._command_ack(
                accepted=False,
                error_code="stale_generation",
                message="Session generation changed",
            )
        except Exception as exc:
            logger.warning(
                "Bilibili room command failed: action={} error_type={}",
                action,
                type(exc).__name__,
            )
            return self._command_ack(
                accepted=False,
                error_code="command_failed",
                message="Room command failed",
            )
        return self._command_ack(
            accepted=True,
            snapshot=snapshot,
            message="Command accepted",
        )

    @staticmethod
    def _parse_expected_generation_id(
        data: dict[str, object] | None,
    ) -> int | None:
        if not isinstance(data, dict) or "expected_generation_id" not in data:
            return None
        value = data["expected_generation_id"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("expected_generation_id must be a non-negative integer")
        return value

    def _command_ack(
        self,
        *,
        accepted: bool,
        error_code: str | None = None,
        message: str,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        current = snapshot or self.session.snapshot()
        return {
            "accepted": accepted,
            "state": str(current["state"]),
            "error_code": error_code,
            "message": message,
        }
