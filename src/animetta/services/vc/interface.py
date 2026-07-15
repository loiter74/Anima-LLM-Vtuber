from __future__ import annotations

"""
Voice Conversion (VC) interface definition
"""

from abc import ABC, abstractmethod
from pathlib import Path


class VCInterface(ABC):
    """
    Abstract base class for voice conversion interfaces.

    Voice conversion transforms the timbre of input audio while
    preserving the linguistic content. Input can be speech, singing,
    or any vocal audio.
    """

    @abstractmethod
    async def convert(
        self, audio: bytes, output_path: str | Path | None = None, **kwargs
    ) -> bytes | str:
        """
        Convert voice timbre of input audio.

        Args:
            audio: Input audio bytes (WAV format)
            output_path: Output file path (optional)
            **kwargs: Additional conversion parameters

        Returns:
            Union[bytes, str]: If output_path is specified, returns the file path string.
                               Otherwise returns converted WAV audio bytes.
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (GPU memory, loaded models, etc.)"""
        pass
