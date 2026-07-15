from __future__ import annotations

"""
Mock TTS implementation - for testing and development
"""

import io
import math
import wave
from pathlib import Path

from animetta.config.core.registry import ProviderRegistry

from .interface import TTSInterface


@ProviderRegistry.register_service("tts", "mock")
class MockTTS(TTSInterface):
    """
    Mock TTS implementation
    Generates a small deterministic WAV tone so downstream audio plumbing is real.
    """

    def __init__(self, sample_rate: int = 24000):
        self._sample_rate = sample_rate

    @classmethod
    def from_config(cls, config, **kwargs):
        """Create instance from configuration (supports ProviderRegistry.create_service path)"""
        return cls()

    async def synthesize(
        self, text: str, output_path: str | Path | None = None, **kwargs
    ) -> bytes | str:
        """Return WAV bytes, or write them to output_path when requested."""
        # Simulate processing delay
        import asyncio

        await asyncio.sleep(0.1)

        audio = self._generate_wav_bytes(text)
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio)
            return str(path)

        return audio

    def _generate_wav_bytes(self, text: str) -> bytes:
        """Generate a short mono PCM WAV tone shaped by text length."""
        duration = min(0.8, max(0.25, len(text) / 80))
        frame_count = int(self._sample_rate * duration)
        frequency = 440.0
        amplitude = 0.18

        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self._sample_rate)
                frames = bytearray()
                for i in range(frame_count):
                    envelope = min(1.0, i / max(1, int(self._sample_rate * 0.03)))
                    sample = int(
                        amplitude
                        * envelope
                        * 32767
                        * math.sin(2 * math.pi * frequency * (i / self._sample_rate))
                    )
                    frames.extend(sample.to_bytes(2, byteorder="little", signed=True))
                wav.writeframes(bytes(frames))
            return buffer.getvalue()

    async def close(self) -> None:
        """No resources to clean up"""
        pass

    @property
    def sample_rate(self) -> int:
        return self._sample_rate
