from __future__ import annotations

"""
GLaDOS-style audio effect processor using SoX effects.

Applies a chain of SoX effects to synthesized TTS audio to produce
an electronic/robotic voice characteristic of Portal 2's GLaDOS.

The default effect chain:
  pitch -> stretch -> overdrive -> chorus -> bandpass -> compand -> gain

Supports two backends:
  1. torchaudio.sox_effects (preferred, Linux/macOS/Conda)
  2. SoX CLI via subprocess (fallback, all platforms including Windows)
"""

# Status: maintained
# Last verified: 2026-05-23

import io
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import torch
import torchaudio
from loguru import logger

# Kokoro's native output sample rate
KOKORO_SAMPLE_RATE = 24000

# Target sample rate for SoX processing
TARGET_SAMPLE_RATE = 24000

# Common SoX installation paths to search
_SOX_CANDIDATE_PATHS: list[str] = [
    # Windows (winget/choco installs)
    r"C:\Program Files (x86)\sox\sox.exe",
    r"C:\Program Files\sox\sox.exe",
    # Windows (Sox download / manual)
    str(Path.home() / "AppData/Local/sox/sox-14.4.2/sox.exe"),
    str(Path.home() / "AppData/Local/sox/sox.exe"),
    # Linux/macOS
    "/usr/bin/sox",
    "/usr/local/bin/sox",
    "/opt/homebrew/bin/sox",
]


def _find_sox() -> str | None:
    """
    Find the sox executable by searching PATH and common locations.

    Returns:
        Full path to sox executable, or None if not found.
    """
    # Try PATH first
    sox_path = os.environ.get("SOX_PATH") or "sox"
    try:
        result = subprocess.run(
            [sox_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Resolve full path
            if os.name == "nt":  # Windows
                where = subprocess.run(
                    ["where", sox_path], capture_output=True, text=True, timeout=5
                )
                if where.returncode == 0:
                    return where.stdout.strip().split("\n")[0].strip()
            return sox_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try candidate paths
    for path in _SOX_CANDIDATE_PATHS:
        if os.path.isfile(path):
            try:
                result = subprocess.run(
                    [path, "--version"], capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return path
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

    return None


def _build_effects_cli_args(params: dict[str, Any]) -> list[str]:
    """
    Build SoX CLI effect arguments from a parameter dict.

    Returns a flat list of CLI args suitable for: sox input.wav output.wav <args>
    """
    args: list[str] = []
    effects_list = _build_effects_list(params)
    for effect in effects_list:
        args.extend(effect)
    return args


def _build_effects_list(params: dict[str, Any]) -> list[list[str]]:
    """
    Build a SoX effects list from a parameter dict.

    The parameter dict keys correspond to SoX effect names.
    Missing keys use standard GLaDOS defaults.

    Args:
        params: Dict with optional keys: enabled, pitch, stretch,
                overdrive, chorus, bandpass, compand, gain

    Returns:
        List of SoX effect argument lists, e.g. [['pitch', '-300'], ...]
    """
    effects: list[list[str]] = []

    # Step 1: Pitch shift (cents, negative = lower)
    pitch = params.get("pitch", -300)
    effects.append(["pitch", str(pitch)])

    # Step 2: Stretch (tempo adjustment, >1 = slower)
    stretch = params.get("stretch", 1.05)
    effects.append(["stretch", f"{stretch:.2f}"])

    # Step 3: Overdrive (distortion, gain in dB)
    overdrive = params.get("overdrive", 20)
    effects.append(["overdrive", str(overdrive)])

    # Step 4: Chorus (electronic resonance)
    chorus_str = params.get("chorus", "0.7 0.9 55 0.4 0.25 2 -t")
    effects.append(["chorus"] + chorus_str.split())

    # Step 5: Bandpass filter (remove natural warmth)
    bandpass_str = params.get("bandpass", "300 3")
    effects.append(["bandpass"] + bandpass_str.split())

    # Step 6: Compand (dynamic range compression)
    compand_str = params.get("compand", "0.3,1 6:-70,-60,-20 -5 -90 0.2")
    effects.append(["compand"] + compand_str.split())

    # Step 7: Output gain adjustment
    gain = params.get("gain", -3)
    effects.append(["gain", str(gain)])

    return effects


class GladosEffectProcessor:
    """
    Applies GLaDOS-style electronic voice effects to audio using SoX.

    The processor supports two backends:
      1. **torchaudio.sox_effects** — in-process Python API (preferred)
      2. **SoX CLI** via subprocess — fallback for Windows and environments
         where torchaudio is built without sox support

    It automatically detects SoX availability and falls back gracefully
    if SoX is not installed.

    Usage:
        processor = GladosEffectProcessor(params)
        processed_audio = await processor.process(raw_audio_bytes)
    """

    def __init__(self, params: dict[str, Any] | None = None):
        """
        Initialize the effect processor.

        Args:
            params: Effect parameters dict. Keys match KokoroTTSConfig.glados_effect.
                    Set params={'enabled': False} to disable.
        """
        self.params = params or {}
        self._enabled = self.params.get("enabled", True) and bool(self.params)
        self._sox_path: str | None = None
        self._sox_available: bool | None = None
        self._using_cli: bool = False

    @property
    def enabled(self) -> bool:
        """Whether effects processing is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def check_sox_available(self) -> bool:
        """
        Check if SoX is available via any backend.

        Returns:
            True if SoX effects can be applied
        """
        if self._sox_available is not None:
            return self._sox_available

        # Method 1: torchaudio.sox_effects (in-process)
        try:
            import torchaudio.sox_effects  # noqa: F401

            test_effects = [["gain", "0"]]
            test_tensor = torch.zeros(1, 2400)
            torchaudio.sox_effects.apply_effects_tensor(test_tensor, 24000, test_effects)
            self._sox_available = True
            self._using_cli = False
            logger.info("[GladosEffect] Backend: torchaudio.sox_effects")
            return True
        except (ImportError, RuntimeError, OSError):
            pass

        # Method 2: SoX CLI via subprocess
        sox_path = _find_sox()
        if sox_path:
            self._sox_path = sox_path
            self._sox_available = True
            self._using_cli = True
            logger.info(f"[GladosEffect] Backend: SoX CLI ({sox_path})")
            return True

        logger.warning(
            "[GladosEffect] SoX not available. "
            "GLaDOS effects will be bypassed. "
            "Install SoX: https://sourceforge.net/projects/sox/files/sox/"
        )
        self._sox_available = False
        return False

    async def _process_via_cli(self, audio_bytes: bytes) -> bytes:
        """Apply effects via SoX CLI subprocess."""
        effects_args = _build_effects_cli_args(self.params)

        # Write input to temp WAV file
        with (
            tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in,
            tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out,
        ):
            tmp_in_path = tmp_in.name
            tmp_out_path = tmp_out.name
            tmp_in.write(audio_bytes)

        try:
            cmd = [
                self._sox_path,
                tmp_in_path,
                tmp_out_path,
                *effects_args,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error(
                    f"[GladosEffect] SoX CLI failed (rc={result.returncode}): {result.stderr[:200]}"
                )
                return audio_bytes

            # Read processed audio
            with open(tmp_out_path, "rb") as f:
                processed = f.read()

            if len(processed) < 100:
                logger.warning("[GladosEffect] SoX output too small, returning raw")
                return audio_bytes

            logger.debug(f"[GladosEffect] CLI: {len(audio_bytes)} -> {len(processed)} bytes")
            return processed

        except subprocess.TimeoutExpired:
            logger.error("[GladosEffect] SoX CLI timed out (30s)")
            return audio_bytes
        except Exception as e:
            logger.error(f"[GladosEffect] CLI processing failed: {e}")
            return audio_bytes
        finally:
            # Cleanup temp files
            try:
                os.unlink(tmp_in_path)
                os.unlink(tmp_out_path)
            except OSError:
                pass

    async def _process_via_torchaudio(self, audio_bytes: bytes) -> bytes:
        """Apply effects via torchaudio.sox_effects in-process API."""
        try:
            buffer = io.BytesIO(audio_bytes)
            waveform, sr = torchaudio.load(buffer)

            effects = _build_effects_list(self.params)

            if sr != TARGET_SAMPLE_RATE:
                effects.append(["rate", str(TARGET_SAMPLE_RATE)])

            processed_waveform, new_sr = torchaudio.sox_effects.apply_effects_tensor(
                waveform, sr, effects
            )

            output_buffer = io.BytesIO()
            torchaudio.save(
                output_buffer,
                processed_waveform,
                new_sr,
                format="wav",
            )
            result = output_buffer.getvalue()

            logger.debug(
                f"[GladosEffect] torchaudio: {len(audio_bytes)} -> {len(result)} bytes, "
                f"sr={sr}->{new_sr}Hz"
            )
            return result

        except Exception as e:
            logger.error(f"[GladosEffect] torchaudio processing failed: {e}")
            return audio_bytes

    async def process(self, audio_bytes: bytes, sample_rate: int = KOKORO_SAMPLE_RATE) -> bytes:
        """
        Apply GLaDOS effects to audio bytes.

        If effects are disabled or SoX is unavailable, returns the original
        audio unchanged.

        Args:
            audio_bytes: Raw WAV audio bytes
            sample_rate: Sample rate of the input audio (default: 24000)

        Returns:
            Processed audio as WAV bytes
        """
        if not self._enabled:
            return audio_bytes

        if not self.check_sox_available():
            logger.debug("[GladosEffect] SoX unavailable, returning raw audio")
            return audio_bytes

        # Guard: skip very short audio (likely empty or noise)
        if len(audio_bytes) < 4096:
            logger.warning(
                f"[GladosEffect] Audio too short ({len(audio_bytes)} bytes), skipping effects"
            )
            return audio_bytes

        if self._using_cli:
            return await self._process_via_cli(audio_bytes)
        else:
            return await self._process_via_torchaudio(audio_bytes)

    async def close(self) -> None:
        """Clean up any resources."""
        pass
