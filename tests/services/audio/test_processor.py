from __future__ import annotations

"""Tests for AudioProcessorInterface — abstract contract enforcement and subclass compliance."""

from unittest.mock import MagicMock

import pytest

from animetta.services.audio.processor import AudioProcessorInterface
from animetta.services.audio.simple_vad_processor import SimpleVADProcessor
from animetta.services.audio.vad_audio_processor import VADAudioProcessor

# ── AudioProcessorInterface — ABC Enforcement ────────────────────────


class TestAudioProcessorInterfaceABC:
    """Enforce that AudioProcessorInterface is a proper ABC."""

    def test_cannot_instantiate_directly(self):
        """Instantiating the ABC directly raises TypeError."""
        with pytest.raises(TypeError):
            AudioProcessorInterface()  # type: ignore[abstract]

    def test_must_implement_process_chunk(self):
        """Subclass missing process_chunk raises TypeError."""

        class Incomplete(AudioProcessorInterface):
            async def process_end(self) -> None:
                pass
            def reset(self) -> None:
                pass
            def is_speaking(self) -> bool:
                return False

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_must_implement_process_end(self):
        """Subclass missing process_end raises TypeError."""

        class Incomplete(AudioProcessorInterface):
            async def process_chunk(self, audio_data) -> None:
                pass
            def reset(self) -> None:
                pass
            def is_speaking(self) -> bool:
                return False

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_must_implement_reset(self):
        """Subclass missing reset raises TypeError."""

        class Incomplete(AudioProcessorInterface):
            async def process_chunk(self, audio_data) -> None:
                pass
            async def process_end(self) -> None:
                pass
            def is_speaking(self) -> bool:
                return False

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_must_implement_is_speaking(self):
        """Subclass missing is_speaking raises TypeError."""

        class Incomplete(AudioProcessorInterface):
            async def process_chunk(self, audio_data) -> None:
                pass
            async def process_end(self) -> None:
                pass
            def reset(self) -> None:
                pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


# ── Complete Subclass — Contract Validation ──────────────────────────


class TestCompleteSubclass:
    """A fully implemented subclass should instantiate and work."""

    @pytest.fixture
    def complete_impl(self):

        class Complete(AudioProcessorInterface):
            def __init__(self):
                self._audio = []
                self._speaking = False
                self._ended = False
                self._chunks_processed = 0

            async def process_chunk(self, audio_data):
                self._audio.extend(audio_data)
                self._speaking = len(audio_data) > 0
                self._chunks_processed += 1

            async def process_end(self):
                self._ended = True
                self._speaking = False

            def reset(self):
                self._audio.clear()
                self._speaking = False
                self._ended = False
                self._chunks_processed = 0

            def is_speaking(self) -> bool:
                return self._speaking

        return Complete()

    @pytest.mark.asyncio
    async def test_process_chunk_appends_audio(self, complete_impl):
        """process_chunk adds data to internal buffer."""
        await complete_impl.process_chunk([0.1, 0.2, 0.3])
        assert complete_impl._audio == [0.1, 0.2, 0.3]
        assert complete_impl._chunks_processed == 1

    @pytest.mark.asyncio
    async def test_process_chunk_empty_does_not_set_speaking(self, complete_impl):
        """Empty chunk → is_speaking should be False."""
        await complete_impl.process_chunk([])
        assert complete_impl.is_speaking() is False

    @pytest.mark.asyncio
    async def test_process_end_sets_ended(self, complete_impl):
        """process_end marks ended and stops speaking."""
        assert complete_impl._ended is False
        await complete_impl.process_end()
        assert complete_impl._ended is True
        assert complete_impl.is_speaking() is False

    def test_reset_clears_all_state(self, complete_impl):
        """reset clears buffer, speaking, ended flags."""
        complete_impl._audio = [0.1, 0.2]
        complete_impl._speaking = True
        complete_impl._ended = True
        complete_impl._chunks_processed = 5
        complete_impl.reset()
        assert complete_impl._audio == []
        assert complete_impl._speaking is False
        assert complete_impl._ended is False
        assert complete_impl._chunks_processed == 0

    def test_is_speaking_initial_false(self, complete_impl):
        """Fresh instance reports not speaking."""
        assert complete_impl.is_speaking() is False

    @pytest.mark.asyncio
    async def test_multiple_chunks_increments_counter(self, complete_impl):
        """Multiple process_chunk calls increment counter."""
        for i in range(3):
            await complete_impl.process_chunk([float(i)])
        assert complete_impl._chunks_processed == 3

    @pytest.mark.asyncio
    async def test_process_end_on_empty_no_error(self, complete_impl):
        """process_end on fresh instance does not crash."""
        await complete_impl.process_end()  # should not raise


# ── VADAudioProcessor — Interface Compliance ────────────────────────


class TestVADAudioProcessorCompliance:
    """VADAudioProcessor implements AudioProcessorInterface correctly."""

    def test_vad_audio_processor_is_subclass(self):
        """VADAudioProcessor inherits from AudioProcessorInterface."""
        assert issubclass(VADAudioProcessor, AudioProcessorInterface)

    def test_vad_audio_processor_implements_all_methods(self):
        """VADAudioProcessor has all 4 required abstract methods."""
        assert hasattr(VADAudioProcessor, 'process_chunk')
        assert hasattr(VADAudioProcessor, 'process_end')
        assert hasattr(VADAudioProcessor, 'reset')
        assert hasattr(VADAudioProcessor, 'is_speaking')

    def test_vad_audio_processor_instantiates(self):
        """VADAudioProcessor can be instantiated (with VAD mock)."""
        mock_vad = MagicMock()
        proc = VADAudioProcessor(session_id="test", vad_engine=mock_vad)
        assert proc is not None
        assert proc.session_id == "test"

    def test_simple_vad_processor_does_not_inherit_interface(self):
        """SimpleVADProcessor does NOT implement AudioProcessorInterface."""
        assert not issubclass(SimpleVADProcessor, AudioProcessorInterface)
