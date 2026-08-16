from __future__ import annotations

"""Lyrics recognition — ASR + .ass generation."""

import asyncio
import re
import tempfile
import wave
from pathlib import Path
from typing import Any

from loguru import logger

from animetta.services.asr.interface import ASRInterface

from .interface import LyricLine


class LyricsGenerator:
    """Generate .ass subtitles from vocals audio."""

    def __init__(
        self,
        model_size: str = "base",
        language: str | None = "zh",
        output_dir: str = "./data/singing/lyrics",
        download_root: str = "E:/anima_data/models/whisper",
        asr_engine: ASRInterface | None = None,
    ):
        self.model_size = model_size
        self.language = language
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.download_root = download_root
        self._asr_engine = asr_engine
        self._model = None

    def _get_model(self):
        """Lazy-load whisper model (kept as instance attr to prevent GC segfault)."""
        if self._model is None:
            import faster_whisper

            self._model = faster_whisper.WhisperModel(
                self.model_size,
                download_root=self.download_root,
            )
        return self._model

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe vocals audio and generate .ass subtitle content."""
        logger.info(f"Transcribing vocals: {audio_path}")

        if self._asr_engine is not None:
            return await self._transcribe_with_shared_asr(audio_path, self._asr_engine)

        model = self._get_model()

        def _do_transcribe():
            transcribe_kwargs: dict = {}
            if self.language:
                transcribe_kwargs["language"] = self.language
            segments_gen, info = model.transcribe(audio_path, **transcribe_kwargs)
            return list(segments_gen), info

        segments, info = await asyncio.to_thread(_do_transcribe)

        ass_lines = self._segments_to_ass(segments)
        ass_content = self._build_ass_header() + "\n".join(ass_lines) + "\n"

        logger.info(f"Transcription complete: {len(segments)} segments")
        return ass_content

    async def _transcribe_with_shared_asr(
        self,
        audio_path: str,
        asr_engine: ASRInterface,
    ) -> str:
        """Use the pooled ASR engine without transferring a large WAV payload."""
        with tempfile.NamedTemporaryFile(
            suffix=".mp3",
            prefix="singing-asr-",
            dir=self.output_dir,
            delete=False,
        ) as compact_file:
            compact_path = Path(compact_file.name)

        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                audio_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                str(compact_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Failed to compact vocals for ASR: {detail}")

            transcript = (
                await asr_engine.transcribe(
                    str(compact_path),
                    audio_format="mp3",
                    language=self.language or "auto",
                )
            ).strip()
            if not transcript:
                raise RuntimeError("Shared ASR returned an empty singing transcript")

            texts = [
                part.strip()
                for part in re.split(r"(?<=[。！？!?])|\r?\n+", transcript)
                if part.strip()
            ]
            duration = await asyncio.to_thread(self._wav_duration_seconds, audio_path)
            lines = [
                LyricLine(
                    text=text,
                    start_ms=round(duration * index / len(texts) * 1000),
                    end_ms=round(duration * (index + 1) / len(texts) * 1000),
                )
                for index, text in enumerate(texts)
            ]
            logger.info(f"Shared ASR transcription complete: {len(lines)} lines")
            return self.build_ass(lines)
        finally:
            compact_path.unlink(missing_ok=True)

    @staticmethod
    def _wav_duration_seconds(audio_path: str) -> float:
        with wave.open(audio_path, "rb") as wav:
            return wav.getnframes() / wav.getframerate()

    def _build_ass_header(self) -> str:
        return """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
Title: Singing Lyrics
Language: zh

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,2,2,30,2,20,20,134

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def build_ass(self, lines: list[LyricLine]) -> str:
        content = self._build_ass_header()
        for line in lines:
            start = self._sec_to_ass_time(line.start_ms / 1000)
            end = self._sec_to_ass_time(line.end_ms / 1000)
            content += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{line.text}\n"
        return content

    def _segments_to_ass(self, segments: list[Any]) -> list[str]:
        lines = []
        for seg in segments:
            start = self._sec_to_ass_time(seg.start)
            end = self._sec_to_ass_time(seg.end)
            text = seg.text.strip()
            if text:
                lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
        return lines

    @staticmethod
    def _sec_to_ass_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds - int(seconds)) * 100 + 0.5)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def parse_lyric_lines(self, ass_content: str) -> list[LyricLine]:
        """Parse .ass content into LyricLine list."""
        lines = []
        for line in ass_content.split("\n"):
            if line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                if len(parts) >= 10:
                    start_str = parts[1].strip()
                    end_str = parts[2].strip()
                    text = parts[9].strip()
                    lines.append(
                        LyricLine(
                            text=text,
                            start_ms=self._ass_time_to_ms(start_str),
                            end_ms=self._ass_time_to_ms(end_str),
                        )
                    )
        return lines

    @staticmethod
    def _ass_time_to_ms(time_str: str) -> int:
        h, m, s = time_str.split(":")
        s, cs = s.split(".")
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(cs) * 10

    @staticmethod
    def parse_lrc(lrc_text: str) -> list[LyricLine]:
        """Parse LRC format into LyricLine list. Handles [mm:ss.xx] format."""
        lines: list[LyricLine] = []
        for line in lrc_text.strip().split("\n"):
            m = re.match(r"\[(\d+):(\d+)\.(\d+)\](.*)", line)
            if m:
                mins, secs, cs, text = int(m[1]), int(m[2]), int(m[3]), m[4].strip()
                if text:
                    start_ms = (mins * 60 + secs) * 1000 + cs * 10
                    lines.append(LyricLine(text=text, start_ms=start_ms, end_ms=0))
        # Fill end_ms: each line ends where next begins
        for i in range(len(lines) - 1):
            lines[i].end_ms = lines[i + 1].start_ms
        if lines:
            lines[-1].end_ms = lines[-1].start_ms + 3000  # 3s default
        return lines

    async def close(self) -> None:
        """Release whisper model to free GPU/CPU memory."""
        if self._model is not None:
            self._model = None
        import gc

        gc.collect()
