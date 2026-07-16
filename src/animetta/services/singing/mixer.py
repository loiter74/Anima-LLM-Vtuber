from __future__ import annotations

"""Audio mixer — blend converted vocals with backing track."""

import asyncio
import subprocess
from pathlib import Path

from loguru import logger


class AudioMixer:
    """Mix vocals and backing track into final output."""

    def __init__(self, output_dir: str = "./data/singing/outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def mix(self, vocals_path: str, backing_path: str, output_name: str = "final.wav") -> str:
        """Mix vocals and backing track using ffmpeg."""
        output_path = self.output_dir / output_name
        logger.info(f"Mixing vocals + backing → {output_path}")

        cmd = [
            "ffmpeg",
            "-i",
            vocals_path,
            "-i",
            backing_path,
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2",
            "-ac",
            "2",
            "-y",
            str(output_path),
        ]

        try:
            result = await asyncio.to_thread(
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg mix failed: {result.stderr[:500]}")

            duration = await self._get_duration(str(output_path))
            logger.info(f"Mix complete: {output_path} ({duration:.1f}s)")
            return str(output_path)

        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found. Install ffmpeg first.") from None

    async def _get_duration(self, audio_path: str) -> float:
        """Get audio duration in seconds using ffprobe."""
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        try:
            result = await asyncio.to_thread(
                lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            )
            return float(result.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired):
            return 0.0

    async def close(self) -> None:
        pass
