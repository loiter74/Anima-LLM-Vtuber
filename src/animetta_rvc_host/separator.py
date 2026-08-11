"""Host-local Demucs source separation for the singing pipeline."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import zipfile
from pathlib import Path


class DemucsHostSeparator:
    """Run the installed Demucs runtime and return a temporary stem archive."""

    def __init__(
        self,
        *,
        python_executable: Path,
        wrapper_path: Path,
        model: str,
        device: str,
        temp_root: Path,
        timeout_seconds: float,
    ) -> None:
        self.python_executable = python_executable.resolve()
        self.wrapper_path = wrapper_path.resolve()
        self.model = model
        self.device = device
        self.temp_root = temp_root.resolve()
        self.timeout_seconds = timeout_seconds
        self._lock = asyncio.Lock()

    async def preload(self) -> None:
        missing = [
            str(path) for path in (self.python_executable, self.wrapper_path) if not path.is_file()
        ]
        if missing:
            raise RuntimeError("Demucs runtime asset(s) missing: " + ", ".join(missing))
        self.temp_root.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            str(self.python_executable),
            "-c",
            "import demucs, numpy, soundfile, torch, torchaudio",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Demucs runtime unavailable: {detail}")

    async def separate(self, audio: bytes) -> Path:
        if len(audio) <= 44:
            raise ValueError("Separation input audio is empty")
        async with self._lock:
            session_dir = Path(tempfile.mkdtemp(prefix="demucs-", dir=self.temp_root))
            source_path = session_dir / "source.wav"
            source_path.write_bytes(audio)
            output_root = session_dir / "stems"
            proc: asyncio.subprocess.Process | None = None
            cmd = [
                str(self.python_executable),
                str(self.wrapper_path),
                "-n",
                self.model,
                "--two-stems",
                "vocals",
                "-d",
                self.device,
                "-j",
                "0",
                "-o",
                str(output_root),
                str(source_path),
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds)
                if proc.returncode != 0:
                    detail = stderr.decode("utf-8", errors="replace")[:1500]
                    raise RuntimeError(f"Demucs separation failed: {detail}")

                stems_dir = output_root / self.model / source_path.stem
                vocals_path = stems_dir / "vocals.wav"
                backing_path = stems_dir / "no_vocals.wav"
                if not vocals_path.is_file() or not backing_path.is_file():
                    raise RuntimeError("Demucs did not produce both required stems")

                archive_path = session_dir / "stems.zip"
                with zipfile.ZipFile(
                    archive_path,
                    mode="w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=1,
                ) as archive:
                    archive.write(vocals_path, "vocals.wav")
                    archive.write(backing_path, "backing.wav")
                return archive_path
            except TimeoutError:
                if proc is not None:
                    proc.kill()
                    await proc.wait()
                shutil.rmtree(session_dir, ignore_errors=True)
                raise
            except Exception:
                shutil.rmtree(session_dir, ignore_errors=True)
                raise

    async def close(self) -> None:
        pass
