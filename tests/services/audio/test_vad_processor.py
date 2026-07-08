from __future__ import annotations

from animetta.services.vad import VADInterface

"""Tests for VADAudioProcessor — chunk buffering, callbacks, timeout."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.services.audio.vad_audio_processor import VADAudioProcessor
from animetta.services.vad import VADState
from animetta.services.vad.interface import VADResult


@pytest.fixture
def mock_vad():
    """A VADInterface mock with detect_speech returning configurable results."""
    vad = MagicMock(spec=VADInterface)
    vad.detect_speech = MagicMock()
    vad.reset = MagicMock()
    vad.get_current_state = MagicMock(return_value=VADState.IDLE)
    return vad


@pytest.fixture
def mock_callbacks():
    return AsyncMock(), AsyncMock()


@pytest.fixture
def processor(mock_vad, mock_callbacks):
    on_start, on_end = mock_callbacks

    return VADAudioProcessor(
        session_id="test-session",
        vad_engine=mock_vad,
        on_speech_start=on_start,
        on_speech_end=on_end,
        sample_rate=16000,
        vad_timeout_seconds=30.0,
    )


def _active_result(is_speech_start=False, is_speech_end=False) -> VADResult:
    return VADResult(
        audio_data=b"",
        is_speech_start=is_speech_start,
        is_speech_end=is_speech_end,
        state=VADState.ACTIVE,
    )


def _idle_result() -> VADResult:
    return VADResult(state=VADState.IDLE)


class TestVADAudioProcessor:
    """Suite for VADAudioProcessor."""

    # ── Chunk buffering ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_chunk_does_nothing(self, processor, mock_vad):
        """An empty chunk should be ignored without calling VAD."""
        await processor.process_chunk([])
        mock_vad.detect_speech.assert_not_called()
        assert len(processor._audio_buffer) == 0

    @pytest.mark.asyncio
    async def test_buffers_audio_on_active(self, processor, mock_vad):
        """Audio data should be buffered when VAD reports ACTIVE."""
        mock_vad.detect_speech.return_value = _active_result()
        await processor.process_chunk([0.1, 0.2, 0.3])
        assert processor._audio_buffer == [0.1, 0.2, 0.3]
        assert processor._total_chunks == 1

    @pytest.mark.asyncio
    async def test_no_vad_engine_buffers_directly(self):
        """Without VAD engine, chunks accumulate directly."""

        p = VADAudioProcessor(session_id="no-vad", vad_engine=None)
        await p.process_chunk([0.5, 0.6])
        assert p._audio_buffer == [0.5, 0.6]
        assert p._total_chunks == 1

    # ── Speech start / end callbacks ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_speech_start_triggers_callback(self, processor, mock_vad, mock_callbacks):
        """is_speech_start=True should call on_speech_start once."""
        on_start, on_end = mock_callbacks
        mock_vad.detect_speech.return_value = _active_result(is_speech_start=True)
        await processor.process_chunk([0.1, 0.2, 0.3])
        on_start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_speech_start_not_duplicated(self, processor, mock_vad, mock_callbacks):
        """Subsequent ACTIVE chunks should not call on_speech_start again."""
        on_start, on_end = mock_callbacks
        mock_vad.detect_speech.side_effect = [
            _active_result(is_speech_start=True),
            _active_result(),
            _active_result(),
        ]
        await processor.process_chunk([0.1])
        await processor.process_chunk([0.2])
        await processor.process_chunk([0.3])
        on_start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_speech_end_triggers_callback(self, processor, mock_vad, mock_callbacks):
        """is_speech_end=True should call on_speech_end with buffered audio."""
        on_start, on_end = mock_callbacks
        mock_vad.detect_speech.return_value = _active_result(is_speech_start=True)
        # Need > 1024 samples to pass the min-buffer-size guard
        await processor.process_chunk([0.1] * 600)
        # Now signal end
        mock_vad.detect_speech.return_value = _active_result(is_speech_end=True)
        await processor.process_chunk([0.4] * 600)
        on_end.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unconfirmed_speech_end_discards_buffer(self, processor, mock_vad, mock_callbacks):
        """speech_detected=False should clear state without invoking on_speech_end."""
        on_start, on_end = mock_callbacks
        mock_vad.detect_speech.side_effect = [
            _active_result(is_speech_start=True),
            VADResult(
                is_speech_end=True,
                state=VADState.IDLE,
                speech_detected=False,
                metadata={"provider": "mimo"},
            ),
        ]

        await processor.process_chunk([0.1] * 600)
        await processor.process_chunk([0.0] * 600)

        on_start.assert_awaited_once()
        on_end.assert_not_called()
        assert processor.is_speaking() is False
        assert processor._audio_buffer == []

    @pytest.mark.asyncio
    async def test_speech_end_not_duplicated(self, processor, mock_vad, mock_callbacks):
        """After speech end, _is_speaking is False so another end should not fire."""
        on_start, on_end = mock_callbacks
        mock_vad.detect_speech.side_effect = [
            _active_result(is_speech_start=True),
            _active_result(is_speech_end=True),
            _active_result(is_speech_end=True),
        ]
        # Need > 1024 samples total for the first end to fire (_handle_speech_end clears _is_speaking)
        await processor.process_chunk([0.1] * 600)
        await processor.process_chunk([0.2] * 600)
        await processor.process_chunk([0.3] * 600)
        on_end.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_speech_end_min_buffer_size(self, processor, mock_vad, mock_callbacks):
        """is_speech_end should NOT fire if buffer has <= 1024 samples."""
        on_start, on_end = mock_callbacks
        mock_vad.detect_speech.side_effect = [
            _active_result(is_speech_start=True),
            _active_result(is_speech_end=True),
        ]
        # Only push 2 samples (well under 1024 threshold)
        await processor.process_chunk([0.1])
        await processor.process_chunk([0.2])
        on_end.assert_not_called()

    # ── 30s timeout ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_force_timeout_ends_speech(self, processor, mock_vad, mock_callbacks):
        """Speaking for > 30s should force speech end."""
        on_start, on_end = mock_callbacks
        mock_vad.detect_speech.return_value = _active_result(is_speech_start=True)

        with patch.object(processor, "_max_audio_duration", 0.001), patch("time.time", side_effect=[100.0, 100.002]):
            await processor.process_chunk([0.1] * 160)  # 10ms of audio

        on_start.assert_awaited_once()
        on_end.assert_awaited_once()

    # ── process_end ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_process_end_fires_speech_end(self, processor, mock_vad, mock_callbacks):
        """process_end should trigger on_speech_end if buffer has data."""
        on_start, on_end = mock_callbacks
        mock_vad.detect_speech.return_value = _active_result(is_speech_start=True)
        await processor.process_chunk([0.1] * 1600)
        # process_end calls _handle_speech_end internally
        await processor.process_end()
        on_end.assert_awaited()

    @pytest.mark.asyncio
    async def test_process_end_empty_buffer(self, processor):
        """process_end with empty buffer should not raise."""
        await processor.process_end()  # should log warning, not crash

    # ── reset / is_speaking ──────────────────────────────────────────

    def test_reset_clears_state(self, processor):
        """reset() should clear audio buffer and VAD state."""
        processor._audio_buffer = [0.1, 0.2]
        processor._is_speaking = True
        processor._vad_active_start_time = 100.0
        processor.reset()
        assert len(processor._audio_buffer) == 0
        assert processor._is_speaking is False
        assert processor._vad_active_start_time is None

    def test_is_speaking(self, processor):
        """is_speaking() should reflect internal state."""
        assert processor.is_speaking() is False
        processor._is_speaking = True
        assert processor.is_speaking() is True

    # ── Internal helpers ─────────────────────────────────────────────

    def test_clear_vad_state(self, processor):
        """_clear_vad_state should reset active tracking."""
        processor._vad_active_start_time = 100.0
        processor._vad_chunk_count = 42
        processor._clear_vad_state()
        assert processor._vad_active_start_time is None
        assert processor._vad_chunk_count == 0

    def test_get_stats(self, processor):
        """get_stats returns a dict with expected keys."""
        processor._total_chunks = 10
        processor._speech_chunks = 3
        processor._audio_buffer = [0.1] * 16000
        stats = processor.get_stats()
        assert stats["total_chunks"] == 10
        assert stats["speech_chunks"] == 3
        assert stats["buffer_size"] == 16000
        assert stats["is_speaking"] is False
        assert stats["buffer_duration"] == pytest.approx(1.0)

    # ── VAD error handling ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_vad_error_does_not_crash(self, processor, mock_vad):
        """VAD errors should be caught and logged, not raised."""
        mock_vad.detect_speech.side_effect = RuntimeError("vad crash")
        await processor.process_chunk([0.1, 0.2])  # should not raise

    @pytest.mark.asyncio
    async def test_vad_idle_clears_state_after_silence(self, processor, mock_vad):
        """IDLE state after speaking should clear VAD state after 2s silence."""
        mock_vad.detect_speech.side_effect = [
            _active_result(is_speech_start=True),
            _active_result(),
            _idle_result(),
        ]
        await processor.process_chunk([0.1])
        processor._last_speech_time = 100.0
        with patch("time.time", return_value=103.0):  # 3s of silence
            mock_vad.detect_speech.side_effect = [_idle_result()]
            await processor.process_chunk([0.2])
        # idle_duration > 2.0 should clear state
        assert processor._vad_active_start_time is None
