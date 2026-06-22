"""
Bilibili danmaku integration handlers.

Manages the DanmakuService lifecycle and processes
incoming danmaku messages through the AI orchestrator.
"""

import asyncio
import time
from typing import TYPE_CHECKING

from loguru import logger

from animetta.services.bilibili import DanmakuService

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
    ):
        self.sio = sio
        self.session_manager = session_manager
        self.admin = admin

        self._bilibili_service = None
        self._main_loop: asyncio.AbstractEventLoop | None = None

    # ── Service lifecycle ─────────────────────────────────────────────

    def start_bilibili(self, room_id: int, sessdata: str = "") -> None:
        """Start Bilibili danmaku service. Stops existing service if running."""

        if self._bilibili_service is not None:
            self.stop_bilibili()

        self._main_loop = asyncio.get_running_loop()
        self._bilibili_service = DanmakuService(
            room_id=room_id,
            sessdata=sessdata,
        )
        self._bilibili_service.set_callback(self._on_danmaku_from_thread)
        self._bilibili_service.set_status_callback(
            self._on_bilibili_status_from_thread
        )
        self._bilibili_service.start()

    def stop_bilibili(self) -> None:
        """Stop Bilibili danmaku service."""
        if self._bilibili_service:
            self._bilibili_service.stop()
            self._bilibili_service = None

    # ── Thread → main-loop dispatch ───────────────────────────────────

    def _on_danmaku_from_thread(self, msg) -> None:
        """Called from Bilibili background thread; schedule on main event loop."""
        if self._main_loop and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._process_danmaku(msg), self._main_loop
            )

    def _on_bilibili_status_from_thread(
        self, connected: bool, message: str
    ) -> None:
        """Called from Bilibili background thread; schedule status emit on main loop."""
        if self._main_loop and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._emit_bilibili_status(connected, message), self._main_loop
            )

    # ── Status broadcast ──────────────────────────────────────────────

    async def _emit_bilibili_status(self, connected: bool, message: str) -> None:
        """Emit Bilibili connection status to all clients."""
        await self.sio.emit(
            EVENTS["bilibili"]["danmaku_status"]["name"],
            {"connected": connected, "message": message},
        )

    # ── Danmaku processing ────────────────────────────────────────────

    async def _process_danmaku(self, msg) -> None:
        """Process a danmaku message in the main event loop."""
        # 1. Broadcast raw danmaku to all clients
        await self.sio.emit(EVENTS["bilibili"]["danmaku"]["name"], msg.to_dict())

        # 2. Process with AI (use a dedicated "bilibili" session)
        try:
            orchestrator = await self.admin._get_or_create_orchestrator(
                "bilibili"
            )
            result = await orchestrator.process_text(
                text=f"{msg.user_name}说: {msg.text}",
                user_id=str(msg.user_id),
                user_name=msg.user_name,
                channel_id="bilibili",
                source=EVENTS["bilibili"]["danmaku"]["name"],
            )

            reply_text = result.get("response_text", "")

            # Broadcast conversation-start
            await self.sio.emit(EVENTS["chat"]["control"]["name"], {"signal": "conversation-start"})

            # Broadcast text response via sentence events
            if reply_text:
                sentence_payload = {
                    "text": reply_text,
                    "seq": 0,
                    "lang": translation_state.source_language.lower()[:2],
                }
                await self.sio.emit(EVENTS["chat"]["sentence"]["name"], sentence_payload)
                await self.sio.emit(
                    EVENTS["chat"]["sentence"]["name"], {"text": "", "is_complete": True}
                )

                # ── Run translation in background (non-blocking) ──
                if translation_state.enabled:

                    async def _translate_danmaku():
                        try:
                            orchestrator_svc = getattr(
                                orchestrator, "service_context", None
                            )
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
                                    t_lang = (
                                        translation_state.target_language.lower()[:2]
                                    )
                                    await self.sio.emit(
                                        EVENTS["chat"]["subtitle_translation"]["name"],
                                        {
                                            "translation": t,
                                            "target_lang": t_lang,
                                        },
                                    )
                                    logger.info(
                                        f"[Bilibili] Translated danmaku reply to "
                                        f"{translation_state.target_language}"
                                    )
                        except Exception as e:
                            logger.warning(
                                f"[Bilibili] Translation failed: {e}"
                            )

                    asyncio.create_task(_translate_danmaku())

            # Broadcast emotion
            emotion = result.get("emotion")
            if emotion:
                await self.sio.emit(EVENTS["chat"]["expression"]["name"], {"emotion": emotion})

            # Broadcast audio
            tts_audio = result.get("tts_audio")
            if tts_audio:
                await self._broadcast_danmaku_audio(tts_audio)

            # Broadcast conversation-end
            await self.sio.emit(EVENTS["chat"]["control"]["name"], {"signal": "conversation-end"})

            # Also emit danmaku.ai_reply for the chat message integration
            if reply_text:
                character_name = "AI"
                persona = (
                    orchestrator.service_context.config.get_persona()
                    if orchestrator.service_context
                    else None
                )
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
        except Exception as e:
            logger.error(f"[Bilibili] Error processing danmaku: {e}")

    # ── Audio broadcasting ────────────────────────────────────────────

    async def _broadcast_danmaku_audio(self, tts_audio) -> None:
        """Process TTS audio and broadcast to all clients."""
        import base64
        import os
        from functools import partial

        loop = asyncio.get_running_loop()

        try:
            audio_data = None
            format = "wav"
            volumes = []

            if isinstance(tts_audio, str) and os.path.exists(tts_audio):
                raw_bytes = await loop.run_in_executor(
                    None, partial(_read_file_bytes, tts_audio)
                )
                ext = os.path.splitext(tts_audio)[1].lower()
                format = ext.lstrip(".") if ext else "wav"
                audio_data = base64.b64encode(raw_bytes).decode("utf-8")
                volumes = _compute_volumes(tts_audio) or []

            elif isinstance(tts_audio, bytes):
                if tts_audio[:4] == b"RIFF":
                    format = "wav"
                elif (
                    tts_audio[:3] == b"ID3"
                    or (tts_audio[0] == 0xFF and (tts_audio[1] & 0xE0) == 0xE0)
                ):
                    format = "mp3"
                elif tts_audio[:4] == b"OggS":
                    format = "ogg"
                audio_data = base64.b64encode(tts_audio).decode("utf-8")
                import tempfile

                tmp_audio = tempfile.mktemp(suffix=f".{format}")
                with open(tmp_audio, "wb") as f:
                    f.write(tts_audio)
                volumes = _compute_volumes(tmp_audio) or []

            if audio_data:
                payload = {"audio_data": audio_data, "format": format}
                if volumes:
                    payload["volumes"] = volumes
                await self.sio.emit(EVENTS["chat"]["audio_with_expression"]["name"], payload)

        except Exception as e:
            logger.error(f"[Bilibili] Audio broadcasting failed: {e}")

    # ── Frontend-initiated Bilibili control ───────────────────────────

    async def on_bilibili_connect(self, sid: str, data: dict) -> None:
        """Handle frontend request to connect to a Bilibili live room."""
        room_id = data.get("room_id")
        if not room_id or not isinstance(room_id, int) or room_id <= 0:
            await self.sio.emit(
                EVENTS["bilibili"]["danmaku_status"]["name"],
                {"connected": False, "message": "Invalid room ID"},
                to=sid,
            )
            return

        try:
            logger.info(
                f"[Bilibili] Frontend requested connect to room {room_id}"
            )
            self.start_bilibili(room_id=room_id)
        except Exception as e:
            logger.error(f"[Bilibili] Error connecting to room {room_id}: {e}")
            await self.sio.emit(
                EVENTS["bilibili"]["danmaku_status"]["name"],
                {"connected": False, "message": str(e)},
                to=sid,
            )

    async def on_bilibili_disconnect(self, sid: str, data: dict) -> None:
        """Handle frontend request to disconnect from Bilibili live room."""
        logger.info("[Bilibili] Frontend requested disconnect")
        self.stop_bilibili()
        await self.sio.emit(
            EVENTS["bilibili"]["danmaku_status"]["name"],
            {"connected": False, "message": "Disconnected by user"},
        )

    async def on_bilibili_update_room(self, sid: str, data: dict) -> None:
        """Handle frontend request to change room ID."""
        room_id = data.get("room_id")
        if not room_id or not isinstance(room_id, int) or room_id <= 0:
            await self.sio.emit(
                EVENTS["bilibili"]["danmaku_status"]["name"],
                {"connected": False, "message": "Invalid room ID"},
                to=sid,
            )
            return

        try:
            logger.info(
                f"[Bilibili] Frontend requested update room to {room_id}"
            )
            self.start_bilibili(room_id=room_id)
            await self.sio.emit(
                EVENTS["bilibili"]["danmaku_status"]["name"],
                {"connected": True, "message": f"Connected to room {room_id}"},
            )
        except Exception as e:
            logger.error(
                f"[Bilibili] Error updating room to {room_id}: {e}"
            )
            await self.sio.emit(
                EVENTS["bilibili"]["danmaku_status"]["name"],
                {"connected": False, "message": str(e)},
                to=sid,
            )
