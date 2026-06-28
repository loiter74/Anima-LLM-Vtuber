from __future__ import annotations

"""
Mock Separation implementation - for testing and development
"""

from pathlib import Path

from animetta.config.core.registry import ProviderRegistry

from .interface import SeparationInterface


@ProviderRegistry.register_service("separation", "mock")
class MockSeparation(SeparationInterface):
    """
    Mock Separation implementation.

    Returns the input audio as both 'vocals' and 'other' stems (identity).
    Used for testing and development.
    """

    def __init__(self):
        pass

    @classmethod
    def from_config(cls, config: MockSeparationConfig, **kwargs):
        """Create instance from configuration."""
        return cls()

    async def separate(
        self,
        audio: bytes,
        target: str | None = None,
        output_dir: str | Path | None = None,
        **kwargs
    ) -> dict[str, bytes | str]:
        """Return audio as mock stems."""
        import asyncio
        await asyncio.sleep(0.1)

        stems = {"vocals": audio, "other": audio}

        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            result = {}
            for stem_name, stem_audio in stems.items():
                out_path = output_dir / f"{stem_name}.wav"
                with open(out_path, "wb") as f:
                    f.write(stem_audio)
                result[stem_name] = str(out_path)
            return result

        return stems

    async def close(self) -> None:
        """No resources to clean up."""
        pass
