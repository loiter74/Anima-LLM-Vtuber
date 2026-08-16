from __future__ import annotations

"""SVC pipeline orchestrator — coordinates all stages."""

import asyncio
import hashlib
import os
import re
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from loguru import logger

from animetta.avatar.analyzers.audio import AudioAnalyzer
from animetta.config.singing import SingingConfig
from animetta.services.asr.interface import ASRInterface

from .bilibili import BilibiliDownloader
from .interface import (
    LyricLine,
    PipelineProgress,
    PipelineStage,
    SingingService,
    SongResult,
)
from .lyrics import LyricsGenerator
from .mixer import AudioMixer
from .rvc_bridge import RVCBridge
from .separator import create_separator
from .svc_bridge import SVCBridge


class SVCPipeline(SingingService):
    """Full SVC pipeline: download → separate → transcribe → SVC → mix."""

    def __init__(self, config: SingingConfig, *, asr_engine: ASRInterface | None = None):
        self.config = config
        self._stage = PipelineStage.IDLE
        self._progress = 0.0
        self._message = ""
        self._cancelled = False
        self._auto_confirm = False
        self._lyrics_ready: asyncio.Event | None = None
        self._confirmed_ass: str | None = None
        self._on_progress: Callable[[PipelineProgress], None] | None = None
        self._session_dir: Path | None = None
        self._source_url: str = ""

        self._downloader = BilibiliDownloader(config.bilibili.output_dir)
        self._separator = create_separator(
            engine=config.separation.engine,
            model=config.separation.model,
            output_dir=config.separation.output_dir,
            base_url=config.separation.base_url,
            api_key=os.getenv(config.separation.api_key_env, ""),
            request_timeout_seconds=config.separation.request_timeout_seconds,
        )
        self._fallback_separator = (
            create_separator(
                engine=config.separation.fallback_engine,
                model=config.separation.model,
                output_dir=config.separation.output_dir,
                base_url=config.separation.base_url,
                api_key=os.getenv(config.separation.api_key_env, ""),
                request_timeout_seconds=config.separation.request_timeout_seconds,
            )
            if config.separation.fallback_engine
            and config.separation.fallback_engine != config.separation.engine
            else None
        )
        self._lyrics_gen = LyricsGenerator(
            model_size=config.asr.model_size,
            language=config.asr.language,
            output_dir=config.asr.output_dir,
            download_root=config.asr.download_root,
            asr_engine=asr_engine,
        )
        self._svc = SVCBridge(config.gpt_sovits)
        self._rvc = (
            RVCBridge(
                rvc_path=config.rvc.rvc_path,
                python_exe=config.rvc.python_exe,
                model_name=config.rvc.model_name,
                index_path=config.rvc.index_path,
                f0_method=config.rvc.f0_method,
                f0_up_key=config.rvc.f0_up_key,
                index_rate=config.rvc.index_rate,
                filter_radius=config.rvc.filter_radius,
                rms_mix_rate=config.rvc.rms_mix_rate,
                protect=config.rvc.protect,
                base_url=config.rvc.base_url,
                api_key=os.getenv(config.rvc.api_key_env, ""),
                expected_revision=config.rvc.expected_revision,
                request_timeout_seconds=config.rvc.request_timeout_seconds,
            )
            if config.rvc.enabled
            else None
        )
        self._mixer = AudioMixer(config.output_dir)

    def set_progress_callback(self, callback: Callable[[PipelineProgress], None]) -> None:
        self._on_progress = callback

    def _update_progress(self, stage: PipelineStage, progress: float, message: str = "") -> None:
        self._stage = stage
        self._progress = progress
        self._message = message
        if self._on_progress:
            self._on_progress(PipelineProgress(stage=stage, progress=progress, message=message))

    async def process(self, url: str, auto_confirm_lyrics: bool = False) -> SongResult:
        """Execute full pipeline from Bilibili URL.

        Args:
            url: Bilibili video URL.
            auto_confirm_lyrics: If True, skip lyrics review and use ASR output directly.
        """
        self._cancelled = False
        self._auto_confirm = auto_confirm_lyrics
        self._source_url = url

        try:
            self._update_progress(PipelineStage.DOWNLOADING, 0, "Starting download...")
            audio_path, video_title, bv_id = await self._downloader.download(url)
            self._check_cancelled()
            self._update_progress(PipelineStage.DOWNLOADING, 100, "Download complete")

            # Save a copy of the original audio as output (root outputs dir for API serving)
            safe_name = self._downloader._sanitize_filename(
                video_title or bv_id or Path(audio_path).stem
            )
            self._init_session(safe_name)
            original_output = Path(self.config.output_dir) / f"{safe_name}_original.wav"
            shutil.copy2(audio_path, str(original_output))

            return await self._run_stages(
                audio_path, video_title=video_title, original_path=str(original_output)
            )

        except asyncio.CancelledError:
            logger.info("Pipeline cancelled")
            self._stage = PipelineStage.IDLE
            raise

    async def process_from_file(
        self,
        local_path: str,
        auto_confirm_lyrics: bool = False,
        provided_lyrics: str = "",
    ) -> SongResult:
        """Execute pipeline from local audio file (skip download).

        Args:
            local_path: Path to local audio file.
            auto_confirm_lyrics: If True, skip lyrics review and use ASR output directly.
        """
        self._cancelled = False
        self._auto_confirm = auto_confirm_lyrics
        self._init_session(str(local_path))
        assert self._session_dir is not None
        source = Path(local_path)
        original_output = (
            Path(self.config.output_dir)
            / f"{self._session_dir.name}_original{source.suffix or '.wav'}"
        )
        shutil.copy2(source, original_output)

        try:
            return await self._run_stages(
                local_path,
                original_path=str(original_output),
                provided_lyrics=provided_lyrics,
            )
        except asyncio.CancelledError:
            logger.info("Pipeline cancelled")
            self._stage = PipelineStage.IDLE
            raise

    def _init_session(self, seed: str) -> None:
        # Generate unique but readable session ID: {clean_name}_{short_hash}
        clean = re.sub(r'[<>:"/\\|?*\s]+', "_", seed)[:40].strip("_") or "session"
        short_hash = hashlib.md5(f"{seed}{datetime.now().isoformat()}".encode()).hexdigest()[:6]
        session_id = f"{clean}_{short_hash}"
        session_output_dir = Path(self.config.output_dir) / session_id
        session_output_dir.mkdir(parents=True, exist_ok=True)
        self._session_dir = session_output_dir

    async def _run_stages(
        self,
        audio_path: str,
        video_title: str = "",
        original_path: str = "",
        provided_lyrics: str = "",
    ) -> SongResult:
        """Run stages 2-6 from an audio file."""
        session_dir = self._session_dir
        if session_dir is None:
            raise RuntimeError("Session not initialized")
        session_id = session_dir.name

        # Stage 2: Separate
        self._update_progress(PipelineStage.SEPARATING, 0, "Separating vocals...")
        try:
            vocals_path, backing_path = await self._separator.separate(audio_path)
        except RuntimeError as error:
            if self._fallback_separator is None:
                raise
            logger.warning(f"Primary separation unavailable: {error}")
            self._update_progress(
                PipelineStage.SEPARATING,
                25,
                "Source separation unavailable; using compatibility audio",
            )
            vocals_path, backing_path = await self._fallback_separator.separate(audio_path)
        self._check_cancelled()
        self._update_progress(PipelineStage.SEPARATING, 100, "Separation complete")

        # Stage 2.5: Try B站 native lyrics first
        lrc = None
        lyric_lines: list[LyricLine]
        lyrics_available = True
        has_provided_lyrics = bool(provided_lyrics.strip())
        if has_provided_lyrics:
            duration = await self._mixer._get_duration(audio_path)
            lyric_lines = self._plain_text_lyrics(provided_lyrics, duration)
            ass_content = self._lyrics_gen.build_ass(lyric_lines)
            self._confirmed_ass = ass_content
            self._update_progress(PipelineStage.TRANSCRIBING, 100, "Using provided lyrics")
        elif self._source_url:
            try:
                lrc = await self._downloader.fetch_lyrics_lrc(self._source_url)
            except Exception as e:
                logger.debug(f"B站 lyrics lookup failed (will use whisper): {e}")

        if has_provided_lyrics:
            pass
        elif lrc:
            lyric_lines = LyricsGenerator.parse_lrc(lrc)
            logger.info(f"Using B站 native lyrics: {len(lyric_lines)} lines")
            # Generate .ass from LRC lines for subtitle display/compatibility
            ass_content = self._lyrics_gen.build_ass(lyric_lines)
            self._confirmed_ass = ass_content
        else:
            # Stage 3: ASR transcription (optional enrichment)
            ass_content, lyrics_available = await self._transcribe_lyrics(vocals_path)

        # Save .ass file
        ass_path = session_dir / "lyrics.ass"
        ass_path.write_text(ass_content, encoding="utf-8")
        subtitle_output_name = f"{session_id}_lyrics.ass"
        subtitle_output_path = Path(self.config.output_dir) / subtitle_output_name
        subtitle_output_path.write_text(ass_content, encoding="utf-8")
        self._message = f"Lyrics saved to {ass_path}"

        # Stage 4: Wait for user confirmation (or auto-confirm)
        if has_provided_lyrics or lrc or not lyrics_available:
            # Provided/native lyrics and unavailable ASR need no review wait.
            pass
        elif self._auto_confirm:
            self._confirmed_ass = ass_content
            self._update_progress(PipelineStage.WAITING_LYRICS, 100, "Lyrics auto-confirmed")
        else:
            self._update_progress(
                PipelineStage.WAITING_LYRICS, 0, "Awaiting lyrics confirmation..."
            )
            self._lyrics_ready = asyncio.Event()
            self._confirmed_ass = None
            await self._lyrics_ready.wait()
            self._check_cancelled()
            self._update_progress(PipelineStage.WAITING_LYRICS, 100, "Lyrics confirmed")

        # Parse lyrics (only for whisper fallback; LRC already parsed)
        if not has_provided_lyrics and not lrc:
            lyric_lines = self._lyrics_gen.parse_lyric_lines(self._confirmed_ass)

        converted_path = session_dir / "converted.wav"
        voice_conversion_applied, voice_identity = await self._convert_voice(
            vocals_path, converted_path
        )

        # Copy converted vocals to outputs for API serving (used for lip sync)
        vocals_output = Path(self.config.output_dir) / f"{session_id}_vocals.wav"
        shutil.copy2(str(converted_path), str(vocals_output))

        # Stage 6: Mix (original vocals)
        self._update_progress(PipelineStage.MIXING, 0, "Mixing audio...")
        final_path = await self._mixer.mix(
            str(converted_path), backing_path, f"{session_id}_final.wav"
        )
        self._check_cancelled()
        self._update_progress(PipelineStage.MIXING, 100, "Original mix complete")

        # Stage 7: Generate TTS vocals using project's GPT-SoVITS voice
        tts_final_path = ""
        try:
            self._update_progress(PipelineStage.MIXING, 0, "Generating TTS voice vocals...")
            tts_final_path = await self._generate_tts_vocals(
                session_dir, backing_path, lyric_lines, session_id
            )
            if tts_final_path:
                self._update_progress(PipelineStage.MIXING, 100, "TTS voice mix complete")
        except Exception as e:
            logger.warning(f"TTS voice generation skipped: {e}")

        # Done
        duration = await self._mixer._get_duration(final_path)
        self._update_progress(PipelineStage.DONE, 100, "Complete!")

        # Compute lip sync volume envelope from vocals track
        volumes: list[float] = []
        try:
            volumes = self._compute_lip_sync_volumes(vocals_path)
            logger.info(f"Lip sync volumes computed: {len(volumes)} samples from isolated vocals")
        except Exception as e:
            logger.warning(f"Failed to compute lip sync volumes: {e}")

        return SongResult(
            audio_path=final_path,
            subtitle_path=str(subtitle_output_path),
            tts_audio_path=tts_final_path,
            original_audio_path=original_path,
            vocals_path=str(vocals_output),
            duration_sec=duration,
            lyrics=lyric_lines,
            video_title=video_title,
            volumes=volumes,
            voice_conversion_applied=voice_conversion_applied,
            voice_provider=voice_identity.get("provider", ""),
            voice_model=voice_identity.get("model", ""),
            voice_revision=voice_identity.get("revision", ""),
            voice_name=voice_identity.get("voice", ""),
        )

    async def _transcribe_lyrics(self, vocals_path: str) -> tuple[str, bool]:
        """Generate subtitles when ASR is available without blocking the song mix."""
        self._update_progress(PipelineStage.TRANSCRIBING, 0, "Transcribing lyrics...")
        try:
            ass_content = await self._lyrics_gen.transcribe(vocals_path)
        except Exception as error:
            logger.warning(
                "Lyrics transcription unavailable; continuing without subtitles: {}",
                error,
            )
            ass_content = self._lyrics_gen.build_ass([])
            self._confirmed_ass = ass_content
            self._update_progress(
                PipelineStage.TRANSCRIBING,
                100,
                "Lyrics unavailable; continuing without subtitles",
            )
            return ass_content, False

        self._check_cancelled()
        self._update_progress(PipelineStage.TRANSCRIBING, 100, "Lyrics ready")
        return ass_content, True

    async def _convert_voice(
        self,
        vocals_path: str,
        converted_path: Path,
    ) -> tuple[bool, dict[str, str]]:
        """Convert vocals and preserve the exact RVC host identity on success."""

        self._update_progress(PipelineStage.CONVERTING, 0, "Converting vocals...")
        try:
            if self._rvc is not None:
                logger.info("Using RVC for voice conversion")
                await self._rvc.convert(vocals_path, str(converted_path))
                identity = self._rvc.last_identity
            else:
                await self._svc.convert(vocals_path, str(converted_path))
                identity = {}
            self._check_cancelled()
            self._update_progress(PipelineStage.CONVERTING, 100, "Conversion complete")
            return True, identity
        except (ConnectionError, OSError, RuntimeError) as error:
            if self._rvc is not None and self.config.rvc.required:
                logger.error(f"Required RVC voice conversion failed: {error}")
                raise RuntimeError(f"Required RVC voice conversion failed: {error}") from error
            logger.warning(f"Voice conversion skipped: {error}")
            shutil.copy2(vocals_path, converted_path)
            self._update_progress(
                PipelineStage.CONVERTING,
                100,
                "Voice conversion skipped — using original vocals",
            )
            return False, {}

    @staticmethod
    def _compute_lip_sync_volumes(vocals_path: str) -> list[float]:
        """Drive mouth movement from isolated vocals while suppressing stem leakage."""
        return AudioAnalyzer().compute_volume_envelope(
            vocals_path,
            normalize=True,
            gain=1.8,
            use_peak=False,
            noise_floor=0.025,
        )

    async def _generate_tts_vocals(
        self,
        session_dir: Path,
        backing_path: str,
        lyric_lines: list[LyricLine],
        session_id: str,
    ) -> str:
        """Generate TTS-processed vocals using the singing pipeline voice.

        The typed ``SingingConfig`` is the only input.  This deliberately avoids
        reopening a second runtime-services file behind the canonical manifest.

        Returns:
            Path to TTS vocal mix file, or empty string on failure.
        """
        tts_cfg = self.config.gpt_sovits
        if not tts_cfg.ref_audio_path:
            logger.info("Singing TTS reference audio is not configured; skipping")
            return ""

        # Concatenate lyrics into text
        full_text = " ".join(line.text for line in lyric_lines if line.text.strip())
        if not full_text:
            logger.warning("No lyrics text for TTS generation")
            return ""

        logger.info(f"Generating singing TTS vocals: {len(full_text)} chars")

        # Call GPT-SoVITS TTS
        try:
            import httpx

            base_url = tts_cfg.base_url
            timeout = httpx.Timeout(600.0, connect=10.0)  # up to 10 min for long singing
            async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout) as client:
                payload = {
                    "text": full_text,
                    "text_lang": tts_cfg.text_lang,
                    "ref_audio_path": tts_cfg.ref_audio_path,
                    "prompt_text": tts_cfg.prompt_text,
                    "prompt_lang": tts_cfg.text_lang,
                    "top_k": tts_cfg.top_k,
                    "top_p": tts_cfg.top_p,
                    "temperature": tts_cfg.temperature,
                    "speed_factor": tts_cfg.speed,
                    "media_type": "wav",
                    "text_split_method": tts_cfg.text_split_method,
                    "sample_steps": 32,
                    "seed": -1,
                }
                resp = await client.post("/tts", json=payload)
                if resp.status_code != 200:
                    logger.warning(
                        f"TTS generation failed (HTTP {resp.status_code}): {resp.text[:200]}"
                    )
                    return ""

                # Save TTS vocals
                tts_vocals_path = session_dir / "tts_vocals.wav"
                tts_vocals_path.write_bytes(resp.content)
                logger.info(f"TTS vocals generated: {tts_vocals_path} ({len(resp.content)} bytes)")
        except Exception as e:
            logger.warning(f"TTS generation failed: {e}")
            return ""

        # Mix TTS vocals with backing track
        try:
            tts_final_path = await self._mixer.mix(
                str(tts_vocals_path), backing_path, f"{session_id}_tts_final.wav"
            )
            logger.info(f"TTS voice mix complete: {tts_final_path}")
            return tts_final_path
        except Exception as e:
            logger.warning(f"TTS mix failed: {e}")
            return ""

    def _check_cancelled(self) -> None:
        if self._cancelled:
            raise asyncio.CancelledError("Pipeline cancelled by user")

    def _plain_text_lyrics(self, text: str, duration_sec: float) -> list[LyricLine]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        duration_ms = max(len(lines), int(duration_sec * 1000))
        step = duration_ms / len(lines)
        return [
            LyricLine(text=line, start_ms=int(index * step), end_ms=int((index + 1) * step))
            for index, line in enumerate(lines)
        ]

    async def cancel(self) -> None:
        self._cancelled = True
        if self._lyrics_ready and not self._lyrics_ready.is_set():
            self._lyrics_ready.set()

    async def confirm_lyrics(self, ass_content: str) -> None:
        self._confirmed_ass = ass_content
        if self._lyrics_ready and not self._lyrics_ready.is_set():
            self._lyrics_ready.set()

    async def get_progress(self) -> PipelineProgress:
        return PipelineProgress(
            stage=self._stage,
            progress=self._progress,
            message=self._message,
        )

    async def close(self) -> None:
        await self._downloader.close()
        await self._separator.close()
        if self._fallback_separator:
            await self._fallback_separator.close()
        await self._lyrics_gen.close()
        await self._svc.close()
        if self._rvc:
            await self._rvc.close()
        await self._mixer.close()
