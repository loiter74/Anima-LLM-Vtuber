"""Audio volume analysis helpers for Live2D lip sync."""

import math
import struct
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from pydub import AudioSegment

    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("[AudioAnalyzer] pydub not available, please run: pip install pydub")


@dataclass(frozen=True)
class _PcmAudioSegment:
    """Small WAV-only fallback that mimics the pydub surface used here."""

    samples: tuple[float, ...]
    frame_rate: int

    def __len__(self) -> int:
        return int(round(len(self.samples) / self.frame_rate * 1000))

    def __getitem__(self, key: slice) -> "_PcmAudioSegment":
        start_ms = 0 if key.start is None else int(key.start)
        stop_ms = len(self) if key.stop is None else int(key.stop)
        start = max(0, int(start_ms * self.frame_rate / 1000))
        stop = max(start, int(stop_ms * self.frame_rate / 1000))
        return _PcmAudioSegment(self.samples[start:stop], self.frame_rate)

    def set_channels(self, channels: int) -> "_PcmAudioSegment":
        if channels != 1:
            raise ValueError("WAV fallback only supports mono output")
        return self

    @property
    def rms(self) -> float:
        if not self.samples:
            return 0.0
        mean_square = sum(sample * sample for sample in self.samples) / len(self.samples)
        return math.sqrt(mean_square) * 32768.0

    @property
    def max(self) -> float:
        if not self.samples:
            return 0.0
        return max(abs(sample) for sample in self.samples) * 32768.0

    def export(self, path: str, format: str = "wav") -> None:
        if format != "wav":
            raise ValueError("WAV fallback can only export wav")
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.frame_rate)
            frames = bytearray()
            for sample in self.samples:
                value = int(max(-1.0, min(1.0, sample)) * 32767)
                frames.extend(struct.pack("<h", value))
            wav.writeframes(bytes(frames))


def _decode_wav_samples(audio_path: str) -> _PcmAudioSegment:
    with wave.open(audio_path, "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frame_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    samples: list[float] = []
    if sample_width == 1:
        values = [(byte - 128) / 128.0 for byte in raw]
    elif sample_width == 2:
        count = len(raw) // 2
        values = [sample / 32768.0 for sample in struct.unpack(f"<{count}h", raw)]
    elif sample_width == 4:
        count = len(raw) // 4
        values = [sample / 2147483648.0 for sample in struct.unpack(f"<{count}i", raw)]
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    for i in range(0, len(values), channels):
        frame = values[i : i + channels]
        if frame:
            samples.append(sum(frame) / len(frame))
    return _PcmAudioSegment(tuple(samples), frame_rate)


class AudioAnalyzer:
    """
    Audio Analyzer

    Calculates RMS volume envelope of audio for Live2D lip sync

    Sample rate: 50 Hz (one sample every 20ms)
    Output range: [0.0, 1.0] (normalized volume)
    """

    # Default sample rate: 50 Hz = one sample every 20ms
    DEFAULT_SAMPLE_RATE = 50  # Hz
    SAMPLE_INTERVAL_MS = 1000 / DEFAULT_SAMPLE_RATE  # 20ms

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE):
        """
        Initialize the audio analyzer

        Args:
            sample_rate: Sample rate (Hz), default 50 Hz
        """
        self.sample_rate = sample_rate
        self.sample_interval_ms = 1000 / sample_rate

    def compute_volume_envelope(
        self,
        audio_path: str,
        normalize: bool = True,
        gain: float = 1.8,
        use_peak: bool = False,
        noise_floor: float = 0.0,
    ) -> list[float]:
        """
        Calculate the volume envelope of audio

        Args:
            audio_path: Audio file path
            normalize: Whether to normalize to [0.0, 1.0]
            gain: Gain factor to boost lip-sync amplitude (default 1.8)
            use_peak: Use peak amplitude instead of RMS (more responsive)
            noise_floor: Absolute linear amplitude below which mouth movement is suppressed

        Returns:
            Volume array, each value represents volume of one sample
        """
        try:
            # Load audio file
            audio = self._load_audio(audio_path)

            # Calculate number of samples
            duration_ms = len(audio)
            num_samples = int(duration_ms / self.sample_interval_ms)

            if num_samples == 0:
                logger.warning(f"[AudioAnalyzer] Audio too short: {audio_path}")
                return []

            # Calculate volume for each sample
            volumes = []
            for i in range(num_samples):
                start_ms = int(i * self.sample_interval_ms)
                end_ms = int((i + 1) * self.sample_interval_ms)

                # Extract segment
                segment = audio[start_ms:end_ms]

                # Use peak amplitude (more responsive) or RMS (smoother)
                if use_peak:
                    volumes.append(float(segment.max) / 32768.0)
                else:
                    volumes.append(float(segment.rms) / 32768.0)

            if noise_floor > 0:
                volumes = [max(0.0, volume - noise_floor) for volume in volumes]

            # Normalize
            if normalize and volumes:
                max_volume = max(volumes)
                if max_volume > 0:
                    volumes = [v / max_volume for v in volumes]
                else:
                    volumes = [0.0] * len(volumes)

            # Apply gain and clamp to [0, 1] range (always, even without normalize)
            if volumes and gain != 1.0:
                volumes = [min(1.0, v * gain) for v in volumes]

            logger.debug(
                f"[AudioAnalyzer] Calculated {len(volumes)} volume samples "
                f"({duration_ms / 1000:.2f}s audio, {self.sample_rate} Hz, "
                f"gain={gain}, noise_floor={noise_floor})"
            )

            return volumes

        except Exception as e:
            logger.warning(f"[AudioAnalyzer] Failed to analyze audio: {e}")
            return []

    def _load_audio(self, audio_path: str) -> Any:
        """
        Load an audio file

        Args:
            audio_path: Audio file path

        Returns:
            AudioSegment object
        """
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        if PYDUB_AVAILABLE:
            # pydub auto-detects format
            audio = AudioSegment.from_file(audio_path)

            # Convert to mono (easier to compute)
            audio = audio.set_channels(1)
            return audio

        if path.suffix.lower() != ".wav":
            raise RuntimeError("pydub is required for non-WAV audio analysis")
        return _decode_wav_samples(audio_path)

    def get_audio_duration(self, audio_path: str) -> float:
        """
        Get audio duration (seconds)

        Args:
            audio_path: Audio file path

        Returns:
            Duration in seconds
        """
        try:
            audio = self._load_audio(audio_path)
            return len(audio) / 1000.0  # ms → s
        except Exception as e:
            logger.error(f"[AudioAnalyzer] Failed to get audio duration: {e}")
            return 0.0


# Convenience function
def compute_volume_envelope(
    audio_path: str, sample_rate: int = 50, gain: float = 1.8
) -> list[float]:
    """
    Convenience function: calculate audio volume envelope

    Args:
        audio_path: Audio file path
        sample_rate: Sample rate (Hz)
        gain: Gain factor

    Returns:
        Volume array [0.0, 1.0]
    """
    analyzer = AudioAnalyzer(sample_rate=sample_rate)
    return analyzer.compute_volume_envelope(audio_path, gain=gain)


def trim_leading_silence(
    audio_path: str,
    threshold: float = 0.005,
    max_scan_ms: int = 500,
    min_trim_ms: int = 50,
) -> str | None:
    """Trim leading silence and return a temporary WAV path, or None if no trim is needed."""
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if PYDUB_AVAILABLE:
        audio = AudioSegment.from_file(audio_path).set_channels(1)
        trim_ms = 0
        for start_ms in range(0, min(max_scan_ms, len(audio)), 10):
            segment = audio[start_ms : start_ms + 10]
            if segment.max / 32768.0 > threshold:
                trim_ms = start_ms
                break
        if trim_ms > min_trim_ms:
            trimmed = audio[trim_ms:]
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp_name = tmp.name
            trimmed.export(tmp_name, format="wav")
            return tmp_name
        return None

    if path.suffix.lower() != ".wav":
        raise RuntimeError("pydub is required for non-WAV silence trimming")

    audio = _decode_wav_samples(audio_path)
    trim_ms = 0
    for start_ms in range(0, min(max_scan_ms, len(audio)), 10):
        segment = audio[start_ms : start_ms + 10]
        if segment.max / 32768.0 > threshold:
            trim_ms = start_ms
            break
    if trim_ms > min_trim_ms:
        trimmed = audio[trim_ms:]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp_name = tmp.name
        trimmed.export(tmp_name, format="wav")
        return tmp_name
    return None
