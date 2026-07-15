from __future__ import annotations

"""
TTS (Text-to-Speech) interface definition
"""

from abc import ABC, abstractmethod
from pathlib import Path


class TTSInterface(ABC):
    """
    Abstract base class for speech synthesis interfaces
    All TTS implementations must inherit from this class and implement its abstract methods
    """

    @abstractmethod
    async def synthesize(
        self, text: str, output_path: str | Path | None = None, **kwargs
    ) -> bytes | str:
        """
        Synthesize text to speech

        Args:
            text: Text to synthesize
            output_path: Output file path (optional)
            **kwargs: Additional parameters

        Returns:
            Union[bytes, str]: If output_path is specified, returns the file path string
                               Otherwise returns audio byte data
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources"""
        pass

    # ── Metadata properties ──────────────────────────────────────────
    # These SHOULD be overridden by implementations but default to
    # common values to avoid breaking existing code.

    @property
    def audio_format(self) -> str:
        """Return the audio format produced by this TTS: 'wav', 'mp3', 'opus', etc."""
        return "wav"

    @property
    def sample_rate(self) -> int:
        """Return the sample rate (Hz) produced by this TTS."""
        return 24000

    @property
    def requires_gpu(self) -> bool:
        """Whether this TTS implementation requires a GPU for reasonable performance."""
        return False
