"""Singing module Socket.IO event handlers."""

import asyncio
import base64
import binascii
import hashlib
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from animetta.config.singing import load_singing_config
from animetta.services.command_inbox import (
    CommandDecision,
    CommandInbox,
    CommandKey,
)
from animetta.services.singing.interface import PipelineProgress
from animetta.services.singing.svc_pipeline import SVCPipeline

from ...socket_events import EVENTS
from .base_handler import BaseSocketHandler

if TYPE_CHECKING:
    from socketio import AsyncServer

    from ..desktop import DesktopClientManager
    from ..live2d import Live2DManager
    from ..session import SessionManager

MAX_SINGING_UPLOAD_BYTES = 64 * 1024 * 1024


class SingingHandlers(BaseSocketHandler):
    """Singing pipeline event handlers."""

    def __init__(
        self,
        sio: "AsyncServer",
        session_manager: "SessionManager",
        desktop_manager: "DesktopClientManager",
        live2d_manager: "Live2DManager",
        command_inbox: CommandInbox | None = None,
    ):
        super().__init__(sio, session_manager, desktop_manager, live2d_manager)
        self._pipeline: SVCPipeline | None = None
        self._active_task_id: str | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._subscribers: dict[str, set[str]] = {}
        self._command_inbox = command_inbox or CommandInbox(":memory:")
        self._start_lock = asyncio.Lock()

    async def on_sing_process(self, sid: str, data: dict) -> None:
        """Start singing pipeline.

        Accepts:
        - { url: "bilibili_url" } for Bilibili download
        - { url: "bilibili_url", auto_confirm: true } to skip lyrics review
        - { file_data: "base64...", file_name: "song.mp3" } for file upload
        - { local_path: "/path/to/audio.wav" } for local file (server-side)
        """
        url = str(data.get("url") or "")
        file_data = str(data.get("file_data") or "")
        file_name = str(data.get("file_name") or "upload.mp3")
        local_path = str(data.get("local_path") or "")
        auto_confirm = data.get("auto_confirm", False)
        task_id = str(data.get("task_id") or uuid.uuid4())
        lyrics_text = str(data.get("lyrics_text") or "")

        if not url and not file_data and not local_path:
            await self.sio.emit(
                EVENTS["sing"]["error"]["name"],
                {
                    "task_id": task_id,
                    "error": "URL, file upload, or local path is required",
                },
                to=sid,
            )
            return

        request = {
            "url": url.strip(),
            "file_sha256": (
                hashlib.sha256(base64.b64decode(file_data, validate=True)).hexdigest()
                if file_data
                else ""
            ),
            "file_name": Path(file_name).name,
            "local_path": local_path,
            "auto_confirm": bool(auto_confirm),
            "lyrics_text": lyrics_text,
        }
        key = CommandKey("dashboard", "singing.process", task_id)
        try:
            accepted = await self._command_inbox.accept(
                key,
                request,
                stored_request={
                    **request,
                    "lyrics_text": "<stored-locally>" if lyrics_text else "",
                },
            )
        except (ValueError, binascii.Error):
            await self._emit_error(task_id, "Singing upload is not valid base64", to=sid)
            return
        if accepted.decision is CommandDecision.CONFLICT:
            await self._emit_error(task_id, "IDEMPOTENCY_CONFLICT", to=sid)
            return
        if accepted.decision is CommandDecision.REPLAY and accepted.task:
            await self.sio.emit(
                EVENTS["sing"]["complete"]["name"], accepted.task.result or {}, to=sid
            )
            return
        if accepted.decision is CommandDecision.TERMINAL and accepted.task:
            await self._emit_error(
                task_id,
                accepted.task.error_code or accepted.task.status.value,
                to=sid,
            )
            return
        self._subscribers.setdefault(task_id, set()).add(sid)
        if accepted.decision is CommandDecision.OBSERVE:
            if accepted.task and accepted.task.progress:
                await self.sio.emit(
                    EVENTS["sing"]["progress"]["name"], accepted.task.progress, to=sid
                )
            return

        async with self._start_lock:
            if self._pipeline is not None:
                await self._command_inbox.fail(
                    key,
                    error_code="RESOURCE_BUSY",
                    error_message="A singing pipeline is already running",
                )
                await self._emit_error(task_id, "RESOURCE_BUSY", to=sid)
                return
            await self._command_inbox.mark_processing(key)
            try:
                config = load_singing_config()

                pipeline = SVCPipeline(config)
                self._pipeline = pipeline
                self._active_task_id = task_id

                def _on_progress(progress: PipelineProgress) -> None:
                    asyncio.ensure_future(self._emit_progress(task_id, progress))

                pipeline.set_progress_callback(_on_progress)

                if file_data:
                    local_path = await self._save_uploaded_file(file_data, file_name)
                    self._run_task = asyncio.create_task(
                        self._run_pipeline(
                            sid,
                            local_audio=local_path,
                            auto_confirm=auto_confirm,
                            task_id=task_id,
                            lyrics_text=lyrics_text,
                        )
                    )
                elif local_path:
                    if not os.path.isfile(local_path):
                        raise FileNotFoundError(f"File not found: {local_path}")
                    self._run_task = asyncio.create_task(
                        self._run_pipeline(
                            sid,
                            local_audio=local_path,
                            auto_confirm=auto_confirm,
                            task_id=task_id,
                            lyrics_text=lyrics_text,
                        )
                    )
                else:
                    self._run_task = asyncio.create_task(
                        self._run_pipeline(
                            sid,
                            url=url,
                            auto_confirm=auto_confirm,
                            task_id=task_id,
                            lyrics_text=lyrics_text,
                        )
                    )
            except Exception as e:
                logger.error(f"sing:process error: {e}", exc_info=True)
                await self._emit_error(task_id, str(e), to=sid)
                await self._command_inbox.fail(
                    key, error_code="SINGING_FAILED", error_message=str(e)
                )
                if self._pipeline is not None:
                    await self._pipeline.close()
                self._pipeline = None
                self._active_task_id = None

    async def _save_uploaded_file(self, file_data: str, file_name: str) -> str:
        """Save base64-encoded file to disk, return path."""
        try:
            raw_bytes = base64.b64decode(file_data, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("Singing upload is not valid base64") from error
        if len(raw_bytes) > MAX_SINGING_UPLOAD_BYTES:
            raise ValueError(f"Singing upload exceeds the {MAX_SINGING_UPLOAD_BYTES} bytes limit")

        upload_dir = Path("./data/singing/uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        output_path = upload_dir / Path(file_name).name

        output_path.write_bytes(raw_bytes)
        logger.info(f"Uploaded file saved: {output_path} ({len(raw_bytes)} bytes)")
        return str(output_path)

    async def _emit_progress(self, *args: object) -> None:
        """Emit progress event to client."""
        if len(args) == 2:
            task_id, progress = args
        elif len(args) == 3:
            sid, task_id, progress = args
            self._subscribers.setdefault(str(task_id), set()).add(str(sid))
        else:
            raise TypeError("_emit_progress expects task_id and progress")
        if not isinstance(task_id, str) or not isinstance(progress, PipelineProgress):
            raise TypeError("invalid singing progress arguments")
        payload = {
            "stage": progress.stage.value,
            "progress": progress.progress,
            "message": progress.message,
            "task_id": task_id,
        }
        await self._command_inbox.update_progress(
            CommandKey("dashboard", "singing.process", task_id), payload
        )
        for subscriber in tuple(self._subscribers.get(task_id, ())):
            await self.sio.emit(EVENTS["sing"]["progress"]["name"], payload, to=subscriber)

        if progress.stage.value == "waiting_lyrics":
            for subscriber in tuple(self._subscribers.get(task_id, ())):
                await self.sio.emit(
                    EVENTS["sing"]["lyrics_ready"]["name"],
                    {"message": progress.message, "task_id": task_id},
                    to=subscriber,
                )

    async def _run_pipeline(
        self,
        sid: str,
        url: str = "",
        local_audio: str = "",
        auto_confirm: bool = False,
        task_id: str = "",
        lyrics_text: str = "",
    ) -> None:
        """Run pipeline in background and emit results."""
        key = CommandKey("dashboard", "singing.process", task_id)
        if (await self._command_inbox.get(key)).decision is CommandDecision.NOT_FOUND:
            await self._command_inbox.accept(key, {"legacy_internal_start": True})
            await self._command_inbox.mark_processing(key)
        try:
            pipeline = self._pipeline
            if pipeline is None:
                return

            if local_audio:
                result = await pipeline.process_from_file(
                    local_audio,
                    auto_confirm_lyrics=auto_confirm,
                    provided_lyrics=lyrics_text,
                )
            else:
                result = await pipeline.process(url, auto_confirm_lyrics=auto_confirm)

            payload = {
                "task_id": task_id,
                "audio_url": f"/api/singing/audio/{os.path.basename(result.audio_path)}",
                "original_url": f"/api/singing/audio/{os.path.basename(result.original_audio_path)}",
                "vocals_url": f"/api/singing/audio/{os.path.basename(result.vocals_path)}",
                "subtitle_url": (
                    f"/api/singing/subtitle/{os.path.basename(result.subtitle_path)}"
                    if result.subtitle_path
                    else ""
                ),
                "tts_audio_url": (
                    f"/api/singing/audio/{os.path.basename(result.tts_audio_path)}"
                    if result.tts_audio_path
                    else ""
                ),
                "video_title": result.video_title,
                "duration": result.duration_sec,
                "voice_conversion_applied": result.voice_conversion_applied,
                "voice_provider": result.voice_provider,
                "voice_model": result.voice_model,
                "voice_revision": result.voice_revision,
                "voice_name": result.voice_name,
                "volumes": result.volumes,  # lip sync envelope from vocals track
                "lyrics": [
                    {
                        "text": line.text,
                        "translation": line.translation,
                        "start_ms": line.start_ms,
                        "end_ms": line.end_ms,
                    }
                    for line in result.lyrics
                ],
            }
            await self._command_inbox.succeed(key, payload)
            subscribers = tuple(self._subscribers.get(task_id, ()))
            if not subscribers:
                await self.sio.emit(EVENTS["sing"]["complete"]["name"], payload)
            for subscriber in subscribers:
                await self.sio.emit(EVENTS["sing"]["complete"]["name"], payload, to=subscriber)
        except asyncio.CancelledError:
            await self._command_inbox.cancel(key)
            await self._emit_error(task_id, "CANCELLED")
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            await self._command_inbox.fail(
                key,
                error_code="SINGING_FAILED",
                error_message=str(e),
            )
            await self._emit_error(task_id, str(e))
        finally:
            if pipeline is not None:
                await pipeline.close()
            if self._pipeline is pipeline:
                self._pipeline = None
                self._active_task_id = None
                self._run_task = None
            self._subscribers.pop(task_id, None)

    async def on_sing_confirm_lyrics(self, sid: str, data: dict) -> dict[str, object]:
        """Confirm lyrics: sing:confirm_lyrics { ass_content: string }"""
        ass_content = data.get("ass_content", "")
        task_id = str(data.get("task_id") or self._active_task_id or "")
        if not self._pipeline or task_id != self._active_task_id:
            return {"ok": False, "task_id": task_id, "error": "TASK_NOT_FOUND"}
        progress = await self._pipeline.get_progress()
        if progress.stage.value != "waiting_lyrics":
            return {"ok": False, "task_id": task_id, "error": "INVALID_TASK_PHASE"}
        if not ass_content:
            return {"ok": False, "task_id": task_id, "error": "INVALID_REQUEST"}
        await self._pipeline.confirm_lyrics(ass_content)
        return {"ok": True, "task_id": task_id, "status": "processing"}

    async def on_sing_cancel(self, sid: str, data: dict) -> dict[str, object]:
        """Cancel pipeline: sing:cancel"""
        task_id = str(data.get("task_id") or self._active_task_id or "")
        if self._pipeline and task_id == self._active_task_id:
            await self._command_inbox.request_cancel(
                CommandKey("dashboard", "singing.process", task_id)
            )
            await self._pipeline.cancel()
        if not task_id:
            return {"ok": False, "error": "TASK_NOT_FOUND"}
        current = await self._command_inbox.get(CommandKey("dashboard", "singing.process", task_id))
        if current.task is None:
            return {"ok": False, "task_id": task_id, "error": "TASK_NOT_FOUND"}
        return {"ok": True, **current.task.snapshot(reused=True)}

    def observe(self, sid: str, task_id: str) -> None:
        self._subscribers.setdefault(task_id, set()).add(sid)

    async def _emit_error(self, task_id: str, error: str, *, to: str | None = None) -> None:
        targets = (to,) if to else tuple(self._subscribers.get(task_id, ()))
        for target in targets:
            await self.sio.emit(
                EVENTS["sing"]["error"]["name"],
                {"task_id": task_id, "error": error},
                to=target,
            )

    async def shutdown(self) -> None:
        if self._pipeline is not None:
            await self._pipeline.cancel()
        if self._run_task is not None:
            await asyncio.gather(self._run_task, return_exceptions=True)

    async def on_sing_subtitle_sync(self, sid: str, data: dict) -> None:
        """Forward subtitle line to all clients.

        Receives: { text: str, translation: str }
        Emits: sing:subtitle_line { text, translation, lang, target_lang }
        """
        text = data.get("text", "")
        translation = data.get("translation", "")
        await self.sio.emit(
            EVENTS["sing"]["subtitle_line"]["name"],
            {
                "text": text,
                "translation": translation,
                "lang": "zh",
                "target_lang": "en",
            },
            to=sid,
        )
