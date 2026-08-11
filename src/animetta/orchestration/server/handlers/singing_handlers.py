"""Singing module Socket.IO event handlers."""

import asyncio
import base64
import binascii
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from loguru import logger

from animetta.config.singing import SingingConfig
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
    ):
        super().__init__(sio, session_manager, desktop_manager, live2d_manager)
        self._pipeline: SVCPipeline | None = None

    async def on_sing_process(self, sid: str, data: dict) -> None:
        """Start singing pipeline.

        Accepts:
        - { url: "bilibili_url" } for Bilibili download
        - { url: "bilibili_url", auto_confirm: true } to skip lyrics review
        - { file_data: "base64...", file_name: "song.mp3" } for file upload
        - { local_path: "/path/to/audio.wav" } for local file (server-side)
        """
        url = data.get("url", "")
        file_data = data.get("file_data", "")
        file_name = data.get("file_name", "upload.mp3")
        local_path = data.get("local_path", "")
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

        if self._pipeline is not None:
            await self.sio.emit(
                EVENTS["sing"]["error"]["name"],
                {"task_id": task_id, "error": "A pipeline is already running"},
                to=sid,
            )
            return

        try:
            config_path = os.path.join(
                os.path.dirname(__file__), "../../../../../config/singing.yaml"
            )
            with open(config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            config = SingingConfig(**raw.get("singing", {}))

            pipeline = SVCPipeline(config)
            self._pipeline = pipeline

            def _on_progress(progress: PipelineProgress) -> None:
                asyncio.ensure_future(self._emit_progress(sid, task_id, progress))

            pipeline.set_progress_callback(_on_progress)

            if file_data:
                # Save uploaded file then run pipeline from local path
                local_path = await self._save_uploaded_file(file_data, file_name)
                asyncio.ensure_future(
                    self._run_pipeline(
                        sid,
                        local_audio=local_path,
                        auto_confirm=auto_confirm,
                        task_id=task_id,
                        lyrics_text=lyrics_text,
                    )
                )
            elif local_path:
                # Direct local file (server-side path)
                if not os.path.isfile(local_path):
                    await self.sio.emit(
                        EVENTS["sing"]["error"]["name"],
                        {"task_id": task_id, "error": f"File not found: {local_path}"},
                        to=sid,
                    )
                    await pipeline.close()
                    self._pipeline = None
                    return
                asyncio.ensure_future(
                    self._run_pipeline(
                        sid,
                        local_audio=local_path,
                        auto_confirm=auto_confirm,
                        task_id=task_id,
                        lyrics_text=lyrics_text,
                    )
                )
            else:
                asyncio.ensure_future(
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
            await self.sio.emit(
                EVENTS["sing"]["error"]["name"],
                {"task_id": task_id, "error": str(e)},
                to=sid,
            )
            if self._pipeline is not None:
                await self._pipeline.close()
            self._pipeline = None

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

    async def _emit_progress(self, sid: str, task_id: str, progress: PipelineProgress) -> None:
        """Emit progress event to client."""
        await self.sio.emit(
            EVENTS["sing"]["progress"]["name"],
            {
                "stage": progress.stage.value,
                "progress": progress.progress,
                "message": progress.message,
                "task_id": task_id,
            },
            to=sid,
        )

        if progress.stage.value == "waiting_lyrics":
            await self.sio.emit(
                EVENTS["sing"]["lyrics_ready"]["name"],
                {
                    "message": progress.message,
                },
                to=sid,
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

            await self.sio.emit(
                EVENTS["sing"]["complete"]["name"],
                {
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
                },
            )
        except asyncio.CancelledError:
            await self.sio.emit(
                EVENTS["sing"]["error"]["name"],
                {"task_id": task_id, "error": "Cancelled"},
                to=sid,
            )
        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            await self.sio.emit(
                EVENTS["sing"]["error"]["name"],
                {"task_id": task_id, "error": str(e)},
                to=sid,
            )
        finally:
            if pipeline is not None:
                await pipeline.close()
            self._pipeline = None

    async def on_sing_confirm_lyrics(self, sid: str, data: dict) -> None:
        """Confirm lyrics: sing:confirm_lyrics { ass_content: string }"""
        ass_content = data.get("ass_content", "")
        if self._pipeline and ass_content:
            await self._pipeline.confirm_lyrics(ass_content)

    async def on_sing_cancel(self, sid: str, data: dict) -> None:
        """Cancel pipeline: sing:cancel"""
        if self._pipeline:
            await self._pipeline.cancel()

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
