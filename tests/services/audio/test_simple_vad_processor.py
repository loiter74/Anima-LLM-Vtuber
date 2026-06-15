from __future__ import annotations

from animetta.services.vad import VADInterface

"""Tests for SimpleVADProcessor — threshold logic, callbacks, state."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.services.audio.simple_vad_processor import SimpleVADProcessor


class _TensorLike:
    """Mimics a PyTorch tensor with .item() for test mocks."""
    def __init__(self, value: float) -> None:
        self._value = value
    def item(self) -> float:
        return self._value


@pytest.fixture
def mock_vad():
    """A VADInterface mock. We'll also give it a mock .model for _get_speech_prob."""
    vad = MagicMock(spec=VADInterface)
    # Simulate a Silero VAD model with __call__ — must return tensor-like with .item()
    model = MagicMock()
    model.return_value = _TensorLike(0.0)  # will be overridden in tests
    vad.model = model
    return vad


@pytest.fixture
def mock_callbacks():
    return AsyncMock()


@pytest.fixture
def processor(mock_vad, mock_callbacks):

    return SimpleVADProcessor(
        session_id="test-simple",
        vad_engine=mock_vad,
        on_speech_end=mock_callbacks,
        threshold=0.5,
        min_speech_duration=0.5,
        min_silence_duration=0.8,
        sample_rate=16000,
    )


class TestSimpleVADProcessor:
    """Suite for SimpleVADProcessor."""

    # ── _get_speech_prob ─────────────────────────────────────────────

    def test_get_speech_prob_no_model(self):
        """Without a silero model, prob returns 0.0."""

        vad_no_model = MagicMock(spec=VADInterface)
        p = SimpleVADProcessor(
            session_id="test", vad_engine=vad_no_model,
            on_speech_end=AsyncMock(),
        )
        assert p._get_speech_prob([0.1, 0.2]) == 0.0

    def test_get_speech_prob_with_model(self, mock_vad):
        """_get_speech_prob delegates to the Silero model."""

        mock_vad.model.return_value = _TensorLike(0.85)
        p = SimpleVADProcessor(
            session_id="test", vad_engine=mock_vad,
            on_speech_end=AsyncMock(),
        )
        prob = p._get_speech_prob([0.1] * 160)
        assert prob == 0.85
        mock_vad.model.assert_called_once()

    def test_get_speech_prob_error_fallback(self, mock_vad):
        """If the model raises, _get_speech_prob returns 0.0."""

        mock_vad.model.side_effect = RuntimeError("model crash")
        p = SimpleVADProcessor(
            session_id="test", vad_engine=mock_vad,
            on_speech_end=AsyncMock(),
        )
        assert p._get_speech_prob([0.1]) == 0.0

    # ── process_chunk speech / silence threshold ─────────────────────

    @pytest.mark.asyncio
    async def test_empty_chunk_ignored(self, processor):
        """Empty chunk returns immediately without buffering."""
        await processor.process_chunk([])
        assert processor._total_chunks == 0

    @pytest.mark.asyncio
    async def test_speech_detected_starts_state(self, processor, mock_vad):
        """Frame above threshold sets _is_speech and _speech_start_time."""
        mock_vad.model.return_value = _TensorLike(0.9)  # above threshold=0.5
        with patch("time.time", return_value=100.0):
            await processor.process_chunk([0.1] * 160)
        assert processor._is_speech is True
        assert processor._speech_start_time == 100.0

    @pytest.mark.asyncio
    async def test_silence_under_threshold(self, processor, mock_vad):
        """Frame below threshold and not in speech does nothing."""
        mock_vad.model.return_value = _TensorLike(0.1)  # below threshold
        # First, get into speech state
        mock_vad.model.return_value = _TensorLike(0.9)
        await processor.process_chunk([0.1] * 160)
        assert processor._is_speech is True
        # Now silence
        mock_vad.model.return_value = _TensorLike(0.1)
        await processor.process_chunk([0.1] * 160)
        assert processor._is_speech is True  # still speaking, silence not long enough
        assert processor._silence_start_time is not None

    @pytest.mark.asyncio
    async def test_silence_ends_speech_after_threshold(
        self, processor, mock_vad, mock_callbacks,
    ):
        """Sufficient silence after sufficient speech triggers on_speech_end."""
        mock_vad.model.return_value = _TensorLike(0.9)
        with patch("time.time", return_value=100.0):
            await processor.process_chunk([0.1] * 160)  # speech starts at t=100

        mock_vad.model.return_value = _TensorLike(0.1)  # silence starts
        with patch("time.time", return_value=100.5):  # first silence chunk
            await processor.process_chunk([0.1] * 160)

        # min_speech_duration=0.5, min_silence_duration=0.8 — need cumulative silence
        # silence_start_time set to 100.5, need total time > 100.5+0.8 = 101.3
        with patch("time.time", return_value=101.5):  # 1.0s of silence accumulated
            await processor.process_chunk([0.1] * 160)

        mock_callbacks.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_silence_too_short_does_not_end(
        self, processor, mock_vad, mock_callbacks,
    ):
        """Short silence (< min_silence_duration) should not end speech."""
        mock_vad.model.return_value = _TensorLike(0.9)
        with patch("time.time", return_value=100.0):
            await processor.process_chunk([0.1] * 160)  # speech starts

        mock_vad.model.return_value = _TensorLike(0.1)
        with patch("time.time", return_value=100.3):  # only 0.3s silence
            await processor.process_chunk([0.1] * 160)

        mock_callbacks.assert_not_called()
        assert processor._is_speech is True

    @pytest.mark.asyncio
    async def test_speech_too_short_does_not_end(
        self, processor, mock_vad, mock_callbacks,
    ):
        """Short speech (< min_speech_duration) should not end even with silence."""
        mock_vad.model.return_value = _TensorLike(0.9)
        with patch("time.time", return_value=100.0):
            await processor.process_chunk([0.1] * 160)  # speech starts

        mock_vad.model.return_value = _TensorLike(0.1)  # silence
        with patch("time.time", return_value=100.2):  # only 0.2s total speech
            await processor.process_chunk([0.1] * 160)

        mock_callbacks.assert_not_called()

    # ── process_end ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_end_fires_callback(self, processor, mock_vad, mock_callbacks):
        """process_end should trigger on_speech_end if in speech."""
        mock_vad.model.return_value = _TensorLike(0.9)
        with patch("time.time", return_value=100.0):
            await processor.process_chunk([0.1] * 160)

        assert processor._is_speech is True
        await processor.process_end()
        mock_callbacks.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_end_no_speech(self, processor, mock_callbacks):
        """process_end when not speaking should not fire callback."""
        await processor.process_end()
        mock_callbacks.assert_not_called()

    # ── reset ────────────────────────────────────────────────────────

    def test_reset_clears_state(self, processor):
        """reset() should clear buffer, speech flag, timers."""
        processor._audio_buffer = [0.1, 0.2]
        processor._is_speech = True
        processor._speech_start_time = 100.0
        processor._silence_start_time = 105.0
        processor.reset()
        assert len(processor._audio_buffer) == 0
        assert processor._is_speech is False
        assert processor._speech_start_time is None
        assert processor._silence_start_time is None

    # ── Edge cases ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rapid_speech_silence_transitions(self, processor, mock_vad, mock_callbacks):
        """Rapid switching between speech and silence should be stable."""
        results = [0.9, 0.1, 0.9, 0.1, 0.9, 0.1]
        timestamps = [100.0, 100.1, 100.2, 100.3, 100.4, 100.5]

        mock_vad.model.side_effect = results
        with patch("time.time", side_effect=timestamps):
            for _ in range(len(results)):
                await processor.process_chunk([0.1] * 160)

        # Each transition resets silence, so no end should fire
        mock_callbacks.assert_not_called()
        assert processor._is_speech is False  # ended in silence

    @pytest.mark.asyncio
    async def test_callback_receives_buffered_audio(self, processor, mock_vad, mock_callbacks):
        """The on_speech_end callback should receive accumulated audio."""
        mock_vad.model.return_value = _TensorLike(0.9)
        with patch("time.time", return_value=100.0):
            await processor.process_chunk([0.1, 0.2, 0.3])

        mock_vad.model.return_value = _TensorLike(0.1)  # first silence, sets silence_start_time
        with patch("time.time", return_value=100.5):
            await processor.process_chunk([0.4])

        # Need cumulative silence > 0.8s — silence_start_time was 100.5
        with patch("time.time", return_value=101.5):  # 1.0s silence accumulated
            await processor.process_chunk([0.5])

        mock_callbacks.assert_awaited_once()
        args = mock_callbacks.await_args[0][0]
        assert 0.1 in args
        assert 0.4 in args
        assert 0.5 in args
