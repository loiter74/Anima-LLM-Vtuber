"""Small dependency-free audio payload validators for TTS boundaries."""

from __future__ import annotations

import io
import wave


def is_valid_audio_payload(audio: bytes, response_format: str) -> bool:
    """Reject empty, mislabeled, or structurally invalid audio payloads."""
    if not audio:
        return False
    normalized = response_format.lower()
    if normalized == "wav":
        return _is_decodable_wav(audio)
    if normalized == "mp3":
        return _has_mp3_container_signature(audio)
    if normalized == "opus":
        return _has_opus_container_signature(audio)
    return False


def _is_decodable_wav(audio: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            if (
                source.getnchannels() < 1
                or source.getsampwidth() < 1
                or source.getframerate() < 1
                or source.getnframes() < 1
            ):
                return False
            return bool(source.readframes(1))
    except (EOFError, OSError, TypeError, ValueError, wave.Error):
        return False


def _has_mp3_container_signature(audio: bytes) -> bool:
    if len(audio) < 4:
        return False
    if audio.startswith(b"ID3"):
        return len(audio) >= 10
    return audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0


def _has_opus_container_signature(audio: bytes) -> bool:
    return len(audio) >= 27 and audio.startswith(b"OggS") and b"OpusHead" in audio[:64]
