"""Thin Socket.IO adapter for the process-owned Bilibili session."""

import asyncio
import time
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from loguru import logger

from animetta.avatar.analyzers.audio import AudioAnalyzer
from animetta.config import ReplyPolicyConfig, SceneAnalysisConfig
from animetta.memory.v2.context import normalize_actor_id
from animetta.services.bilibili import (
    DanmakuBuffer,
    DanmakuMessage,
    DanmakuReplyRuntime,
    LivestreamEvent,
    LivestreamSession,
    ReplyCandidate,
    ReplyMetrics,
)
from animetta.services.bilibili.livestream_session import StaleGenerationError
from animetta.services.scene_analysis import SceneModelGateway, SceneRuntime
from animetta.utils.tempfiles import write_temp_bytes

from ...chat_contracts import ChatIdentity, ChatTransportMode
from ...chat_delivery import ChatDelivery
from ...socket_events import EVENTS

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..session import SessionManager
    from .base_handler import BaseSocketHandler


def _read_file_bytes(path: str) -> bytes:
    """Read an audio file for transport from a worker thread."""
    with open(path, "rb") as audio_file:
        return audio_file.read()


def _compute_volumes(audio_path: str) -> list[float]:
    """Build the non-normalized peak envelope used by Live2D lip sync."""
    return AudioAnalyzer().compute_volume_envelope(
        audio_path,
        normalize=False,
        gain=3.5,
        use_peak=True,
    )


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
        return await self.session.stop(expected_generation_id=expected_generation_id)

    # ── Status broadcast ──────────────────────────────────────────────

    async def emit_status_snapshot(self, payload: dict[str, object]) -> None:
        """Broadcast one authoritative session snapshot to all clients."""
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
        await self._process_ai_reply(candidate.message, candidate.room_id)

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

    async def _process_ai_reply(
        self,
        msg: DanmakuMessage,
        room_id: int,
    ) -> None:
        """Generate and deliver one already-admitted AI reply."""
        from ...graph.translation_state import translation_state

        try:
            task_id = str(uuid4())
            identity = ChatIdentity(
                message_id=str(uuid4()),
                conversation_id=str(uuid4()),
                task_id=task_id,
                turn_id=task_id,
            )
            delivery = ChatDelivery(self.sio, identity, ChatTransportMode.CANONICAL)
            orchestrator = await self.admin._get_or_create_orchestrator("bilibili")
            scene_metadata: dict[str, object] = {}
            if self.scene_runtime is not None:
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
            actor_id = normalize_actor_id(msg.user_id, "bilibili")
            stream_id = f"bilibili:{room_id}" if room_id else None
            result = await orchestrator.process_text(
                text=f"{msg.user_name}说: {msg.text}",
                user_id=actor_id,
                user_name=msg.user_name,
                channel_id="bilibili",
                source=EVENTS["bilibili"]["danmaku"]["name"],
                message_id=identity.message_id,
                conversation_id=identity.conversation_id,
                task_id=identity.task_id,
                turn_id=identity.task_id,
                transport_mode=ChatTransportMode.CANONICAL.value,
                channel="bilibili",
                stream_id=stream_id,
                live_session_id=self.admin.live_session_id,
                actor_role="viewer",
                audience="livestream",
                **cast(dict[str, Any], scene_metadata),
            )

            reply_text = result.get("response_text", "")

            # Broadcast conversation-start
            await delivery.emit("chat", "control", {"signal": "conversation-start"})

            # Broadcast text response via sentence events
            if reply_text:
                sentence_payload = {
                    "text": reply_text,
                    "seq": 0,
                    "lang": translation_state.source_language.lower()[:2],
                }
                await delivery.emit("chat", "sentence", sentence_payload)
                await delivery.emit(
                    "chat",
                    "sentence",
                    {
                        "text": "",
                        "seq": 1,
                        "lang": sentence_payload["lang"],
                        "is_complete": True,
                    },
                )

                # ── Run translation in background (non-blocking) ──
                if translation_state.enabled:

                    async def _translate_danmaku():
                        try:
                            orchestrator_svc = getattr(orchestrator, "service_context", None)
                            llm = (
                                getattr(orchestrator_svc, "llm_engine", None)
                                if orchestrator_svc
                                else None
                            )
                            if llm:
                                translate_prompt = (
                                    f"Translate the following text from {translation_state.source_language} "
                                    f"to {translation_state.target_language}. "
                                    f"Output only the translation, no explanations, no quotes.\n\n"
                                    f"Text: {reply_text}\n"
                                    f"Translation:"
                                )
                                translated = await llm.chat(translate_prompt)
                                if translated and translated.strip():
                                    t = translated.strip()
                                    t_lang = translation_state.target_language.lower()[:2]
                                    await delivery.emit(
                                        "chat",
                                        "subtitle_translation",
                                        {
                                            "translation": t,
                                            "target_lang": t_lang,
                                        },
                                    )
                                    logger.info(
                                        f"[Bilibili] Translated danmaku reply to "
                                        f"{translation_state.target_language}"
                                    )
                        except Exception as exc:
                            logger.warning(
                                "Bilibili translation failed: error_type={}",
                                type(exc).__name__,
                            )

                    # Translation is part of the generation-owned reply task so a
                    # room switch or stop cancels it with the reply worker.
                    await _translate_danmaku()

            # Broadcast emotion
            emotion = result.get("emotion")
            if emotion:
                await delivery.emit("chat", "expression", {"emotion": emotion})

            # Broadcast audio
            tts_audio = result.get("tts_audio")
            if tts_audio:
                await self._broadcast_danmaku_audio(tts_audio, delivery)

            # Broadcast conversation-end
            await delivery.emit("chat", "control", {"signal": "conversation-end"})

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
                    },
                )
            if reply_text and self.scene_runtime is not None:
                try:
                    await self.scene_runtime.record_host_reply(reply_text)
                except Exception as exc:
                    logger.warning(
                        "Scene host-reply feedback failed: error_type={}",
                        type(exc).__name__,
                    )
        except Exception as exc:
            logger.error(
                "Bilibili reply processing failed: error_type={}",
                type(exc).__name__,
            )
            raise

    # ── Audio broadcasting ────────────────────────────────────────────

    async def _broadcast_danmaku_audio(
        self,
        tts_audio: str | bytes,
        delivery: ChatDelivery,
    ) -> None:
        """Process TTS audio and broadcast to all clients."""
        import base64
        import os
        from functools import partial

        loop = asyncio.get_running_loop()

        try:
            audio_data = None
            format = "wav"
            volumes: list[float] = []

            if isinstance(tts_audio, str) and os.path.exists(tts_audio):
                raw_bytes = await loop.run_in_executor(None, partial(_read_file_bytes, tts_audio))
                ext = os.path.splitext(tts_audio)[1].lower()
                format = ext.lstrip(".") if ext else "wav"
                audio_data = base64.b64encode(raw_bytes).decode("utf-8")
                volumes = _compute_volumes(tts_audio) or []

            elif isinstance(tts_audio, bytes):
                if tts_audio[:4] == b"RIFF":
                    format = "wav"
                elif tts_audio[:3] == b"ID3" or (
                    tts_audio[0] == 0xFF and (tts_audio[1] & 0xE0) == 0xE0
                ):
                    format = "mp3"
                elif tts_audio[:4] == b"OggS":
                    format = "ogg"
                audio_data = base64.b64encode(tts_audio).decode("utf-8")
                tmp_audio = write_temp_bytes(tts_audio, suffix=f".{format}")
                volumes = _compute_volumes(tmp_audio) or []

            if audio_data:
                payload: dict[str, Any] = {"audio_data": audio_data, "format": format}
                if volumes:
                    payload["volumes"] = volumes
                await delivery.emit("chat", "audio_with_expression", payload)

        except Exception as exc:
            logger.error(
                "Bilibili audio broadcasting failed: error_type={}",
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
