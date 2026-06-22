"""Tests for VAD factory and mock implementation."""

from __future__ import annotations

import numpy as np
import pytest

from animetta.services.vad.factory import VADFactory
from animetta.services.vad.interface import VADInterface, VADState
from animetta.services.vad.mock_vad import MockVAD


class TestVADFactory:
    def test_create_mock(self):
        engine = VADFactory.create("mock")
        assert isinstance(engine, VADInterface)

    def test_create_unknown_returns_mock(self):
        engine = VADFactory.create("nonexistent_provider")
        assert isinstance(engine, MockVAD)

    def test_create_mock_with_params(self):
        engine = VADFactory.create("mock", sample_rate=8000, db_threshold=-20.0)
        assert isinstance(engine, MockVAD)
        assert engine.sample_rate == 8000
        assert engine.db_threshold == -20.0


class TestMockVAD:
    def test_initial_state(self):
        vad = MockVAD()
        assert vad.get_current_state() == VADState.IDLE

    def test_detect_speech_silence(self):
        vad = MockVAD(min_speech_duration=1)
        result = vad.detect_speech(np.zeros(16000, dtype=np.float32))
        assert result.is_speech_start is False
        assert result.is_speech_end is False

    def test_reset(self):
        vad = MockVAD()
        vad.detect_speech(np.ones(16000, dtype=np.float32) * 0.5)
        vad.reset()
        assert vad.get_current_state() == VADState.IDLE

    @pytest.mark.asyncio
    async def test_close_does_not_raise(self):
        vad = MockVAD()
        await vad.close()
