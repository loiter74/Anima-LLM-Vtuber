from __future__ import annotations

"""
Mock TTS implementation - for testing and development
"""

from pathlib import Path

from animetta.config.core.registry import ProviderRegistry

from .interface import TTSInterface


@ProviderRegistry.register_service("tts", "mock")
class MockTTS(TTSInterface):
    """
    Mock TTS implementation
    Does not perform actual speech synthesis, returns a simulated audio path
    """

    def __init__(self, mock_audio_path: str = "/cache/mock_audio.wav"):
        self.mock_audio_path = mock_audio_path

    @classmethod
    def from_config(cls, config, **kwargs):
        """Create instance from configuration (supports ProviderRegistry.create_service path)"""
        return cls()

    async def synthesize(
        self,
        text: str,
        output_path: str | Path | None = None,
        **kwargs
    ) -> bytes | str:
        """Return simulated audio path"""
        # Simulate processing delay
        import asyncio
        await asyncio.sleep(0.1)

        if output_path:
            # If output path is specified, return that path
            return str(output_path)

        # Otherwise return the mock path
        return self.mock_audio_path

    async def close(self) -> None:
        """No resources to clean up"""
        pass
