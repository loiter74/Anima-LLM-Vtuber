from __future__ import annotations

"""Source separation — supports Demucs (default) and UVR."""

import asyncio
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from uuid import uuid4

from loguru import logger


class BaseSeparator(ABC):
    """Abstract base for source separation engines."""

    def __init__(self, output_dir: str = "./data/singing/separated"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def separate(self, audio_path: str) -> tuple[str, str]:
        """Separate audio into (vocals_path, backing_path)."""
        ...

    async def close(self) -> None:
        pass


class DemucsSeparator(BaseSeparator):
    """Separate vocals from backing track using Demucs."""

    def __init__(
        self,
        model: str = "htdemucs",
        output_dir: str = "./data/singing/separated",
    ):
        super().__init__(output_dir)
        self.model = model

    async def separate(self, audio_path: str) -> tuple[str, str]:
        """Separate audio into vocals and backing track.

        Returns:
            Tuple of (vocals_path, backing_path).
        """
        logger.info(f"Separating audio: {audio_path} (model={self.model})")

        session_dir = self.output_dir / Path(audio_path).stem
        session_dir.mkdir(parents=True, exist_ok=True)

        vocals_path = session_dir / "vocals.wav"
        backing_path = session_dir / "backing.wav"

        if vocals_path.exists() and backing_path.exists():
            logger.info(f"Using cached separation: {session_dir}")
            return str(vocals_path), str(backing_path)

        # Demucs separates into model_dir/original_name/stem.wav
        # Use wrapper script to bypass torchcodec incompatibility with torch 2.11+
        project_root = Path(__file__).parent.parent.parent.parent.parent
        demucs_wrapper = project_root / "scripts" / "demucs_fix.py"
        if demucs_wrapper.exists():
            cmd = [
                sys.executable,
                str(demucs_wrapper),
                "-n",
                self.model,
                "--two-stems",
                "vocals",
                "-d",
                "cpu",
                "-o",
                str(session_dir),
                audio_path,
            ]
        else:
            cmd = [
                sys.executable,
                "-m",
                "demucs",
                "-n",
                self.model,
                "--two-stems",
                "vocals",
                "-d",
                "cpu",
                "-o",
                str(session_dir),
                audio_path,
            ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "TORCHAUDIO_BACKEND": "soundfile"},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

            if proc.returncode != 0:
                err_text = (
                    stderr.decode("utf-8", errors="replace")[:500] if stderr else "(no output)"
                )
                raise RuntimeError(f"Demucs failed (code {proc.returncode}): {err_text}")

            # Demucs output: <session_dir>/<model>/<song_name>/vocals.wav + no_vocals.wav
            original_stem = Path(audio_path).stem
            demucs_output = session_dir / self.model / original_stem
            src_vocals = demucs_output / "vocals.wav"
            src_backing = demucs_output / "no_vocals.wav"

            if not src_vocals.exists():
                raise RuntimeError(f"Demucs vocals not found: {src_vocals}")
            if not src_backing.exists():
                raise RuntimeError(f"Demucs backing not found: {src_backing}")

            # Copy to expected locations
            shutil.copy2(src_vocals, vocals_path)
            shutil.copy2(src_backing, backing_path)

            logger.info(f"Separation complete: vocals={vocals_path}, backing={backing_path}")
            return str(vocals_path), str(backing_path)

        except TimeoutError:
            raise RuntimeError("Demucs processing timed out (>10 min)")


class UVRSeparator(BaseSeparator):
    """Separate vocals using audio-separator (UVR models via ONNX)."""

    def __init__(
        self, model: str = "UVR-MDX-NET-Inst_HQ_3", output_dir: str = "./data/singing/separated"
    ):
        super().__init__(output_dir)
        self.model = model

    async def separate(self, audio_path: str) -> tuple[str, str]:
        """Separate audio into vocals and backing track using audio-separator.

        Returns:
            Tuple of (vocals_path, backing_path).
        """
        logger.info(f"Separating audio (audio-separator): {audio_path} (model={self.model})")

        session_dir = self.output_dir / Path(audio_path).stem
        session_dir.mkdir(parents=True, exist_ok=True)

        vocals_path = session_dir / "vocals.wav"
        backing_path = session_dir / "backing.wav"

        if vocals_path.exists() and backing_path.exists():
            logger.info(f"Using cached separation: {session_dir}")
            return str(vocals_path), str(backing_path)

        import asyncio

        def _do_separate():
            from audio_separator.separator import Separator

            sep = Separator(output_dir=str(session_dir))
            # Use the specified model, fall back to built-in defaults
            output = sep.separate(audio_path)
            return output

        try:
            await asyncio.to_thread(_do_separate)
            # audio-separator outputs (vocals, instrumental)
            # Find the generated files
            inst_files = list(session_dir.glob("*(Instrumental)*.wav")) + list(
                session_dir.glob("*(no_vocals)*.wav")
            )
            vocal_files = list(session_dir.glob("*(Vocals)*.wav")) + list(
                session_dir.glob("*(vocals)*.wav")
            )

            if vocal_files:
                shutil.copy2(vocal_files[0], vocals_path)
            if inst_files:
                shutil.copy2(inst_files[0], backing_path)

            if not vocals_path.exists():
                # Try looking for any output
                all_wavs = list(session_dir.glob("*.wav"))
                if len(all_wavs) >= 2:
                    shutil.copy2(all_wavs[0], vocals_path)
                    shutil.copy2(all_wavs[1], backing_path)

            logger.info(f"audio-separator complete: vocals={vocals_path}, backing={backing_path}")
            return str(vocals_path), str(backing_path)

        except Exception as e:
            raise RuntimeError(f"audio-separator failed: {e}")


class HostDemucsSeparator(BaseSeparator):
    """Call the authenticated Windows host Demucs service."""

    def __init__(
        self,
        *,
        model: str,
        output_dir: str,
        base_url: str,
        api_key: str,
        request_timeout_seconds: float,
    ) -> None:
        super().__init__(output_dir)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.request_timeout_seconds = request_timeout_seconds

    async def separate(self, audio_path: str) -> tuple[str, str]:
        if not self.base_url or not self.base_url.startswith(("http://", "https://")):
            raise RuntimeError("Host Demucs base URL is unavailable")
        if not self.api_key:
            raise RuntimeError("Host Demucs API key is unavailable")
        source = Path(audio_path)
        if not source.is_file() or source.stat().st_size <= 44:
            raise RuntimeError(f"Host Demucs input audio is unavailable: {source}")

        session_dir = self.output_dir / source.stem
        vocals_path = session_dir / "vocals.wav"
        backing_path = session_dir / "backing.wav"
        if vocals_path.is_file() and backing_path.is_file():
            return str(vocals_path), str(backing_path)

        session_dir.mkdir(parents=True, exist_ok=True)
        try:
            await asyncio.to_thread(
                self._request_remote,
                source,
                session_dir,
                vocals_path,
                backing_path,
            )
        except Exception:
            vocals_path.unlink(missing_ok=True)
            backing_path.unlink(missing_ok=True)
            raise
        logger.info(
            f"Host Demucs complete: vocals={vocals_path}, backing={backing_path}, "
            f"model={self.model}"
        )
        return str(vocals_path), str(backing_path)

    def _request_remote(
        self,
        source: Path,
        session_dir: Path,
        vocals_path: Path,
        backing_path: Path,
    ) -> None:
        request_id = str(uuid4())
        headers = {
            "Accept": "application/zip",
            "Content-Type": "application/octet-stream",
            "X-Request-ID": request_id,
            "X-Separation-Model": self.model,
            "Authorization": f"Bearer {self.api_key}",
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/separate",
            data=source.read_bytes(),
            headers=headers,
            method="POST",
        )
        archive_path = session_dir / "stems.zip"
        try:
            with urllib.request.urlopen(  # noqa: S310 - configured local host service
                request,
                timeout=self.request_timeout_seconds,
            ) as response:
                actual_model = response.headers.get("X-Separation-Model", "")
                if actual_model != self.model:
                    raise RuntimeError("Host Demucs model identity mismatch")
                with archive_path.open("wb") as archive_file:
                    shutil.copyfileobj(response, archive_file)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Host Demucs HTTP {error.code}: {detail}") from error
        except (OSError, urllib.error.URLError) as error:
            raise ConnectionError(f"Host Demucs unavailable: {error}") from error

        try:
            with zipfile.ZipFile(archive_path) as archive:
                if not {"vocals.wav", "backing.wav"}.issubset(archive.namelist()):
                    raise RuntimeError("Host Demucs returned an invalid stem archive")
                with archive.open("vocals.wav") as source_file, vocals_path.open("wb") as target:
                    shutil.copyfileobj(source_file, target)
                with archive.open("backing.wav") as source_file, backing_path.open("wb") as target:
                    shutil.copyfileobj(source_file, target)
        except (OSError, zipfile.BadZipFile) as error:
            raise RuntimeError("Host Demucs returned an invalid stem archive") from error
        finally:
            archive_path.unlink(missing_ok=True)


class FFmpegSeparator(BaseSeparator):
    """Compatibility separator that keeps the full mix as vocals.

    This preserves an executable pipeline in lightweight runtimes. It is an
    explicit fallback, not a replacement for Demucs/UVR source separation.
    """

    async def separate(self, audio_path: str) -> tuple[str, str]:
        session_dir = self.output_dir / Path(audio_path).stem
        session_dir.mkdir(parents=True, exist_ok=True)
        vocals_path = session_dir / "vocals.wav"
        backing_path = session_dir / "backing.wav"

        if vocals_path.exists() and backing_path.exists():
            return str(vocals_path), str(backing_path)

        await self._run_ffmpeg(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                audio_path,
                "-map",
                "0:a:0",
                "-ac",
                "2",
                "-ar",
                "44100",
                "-y",
                str(vocals_path),
            ],
            "audio compatibility conversion",
        )
        await self._run_ffmpeg(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(vocals_path),
                "-af",
                "volume=0",
                "-y",
                str(backing_path),
            ],
            "silent backing generation",
        )
        logger.warning("Using FFmpeg compatibility separation; source vocals are not isolated")
        return str(vocals_path), str(backing_path)

    @staticmethod
    async def _run_ffmpeg(cmd: list[str], operation: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found. Install ffmpeg first.") from None
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"FFmpeg {operation} failed: {detail}")


def create_separator(
    engine: str,
    model: str,
    output_dir: str,
    *,
    base_url: str = "",
    api_key: str = "",
    request_timeout_seconds: float = 1200.0,
) -> BaseSeparator:
    """Factory: create source separator by engine name.

    Args:
        engine: "host-demucs", "demucs", "uvr", or "ffmpeg"
        model: Model name (e.g. "htdemucs" or "UVR-MDX-NET-Inst_HQ_3")
        output_dir: Output directory path
    """
    if engine == "uvr":
        return UVRSeparator(model=model, output_dir=output_dir)
    if engine == "ffmpeg":
        return FFmpegSeparator(output_dir=output_dir)
    if engine == "host-demucs":
        return HostDemucsSeparator(
            model=model,
            output_dir=output_dir,
            base_url=base_url,
            api_key=api_key,
            request_timeout_seconds=request_timeout_seconds,
        )
    return DemucsSeparator(model=model, output_dir=output_dir)


# Alias for backward compatibility
SourceSeparator = DemucsSeparator
