from __future__ import annotations

"""
ASR (Automatic Speech Recognition) interface definition
"""

from abc import ABC, abstractmethod
from pathlib import Path


class ASRInterface(ABC):
    """
    Abstract base class for speech recognition interfaces
    All ASR implementations must inherit from this class and implement its abstract methods
    """

    @abstractmethod
    async def transcribe(self, audio_data: bytes | str | Path, **kwargs) -> str:
        """
        Transcribe audio data to text

        Args:
            audio_data: Audio data, can be:
                - bytes: Raw audio bytes
                - str/Path: Audio file path
            **kwargs: Additional parameters

        Returns:
            str: Recognized text
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources"""
        pass
