"""Tests for VAD factory and mock implementation."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from animetta.config.providers.vad import MimoVADConfig
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

    def test_strict_unknown_provider_fails_without_constructing_mock(self):
        with (
            patch(
                "animetta.services.vad.factory.MockVAD",
                side_effect=AssertionError("MockVAD must not be constructed"),
            ),
            pytest.raises(ValueError, match="Unknown VAD provider"),
        ):
            VADFactory.create("nonexistent_provider", strict=True)

    def test_strict_registry_failure_propagates_without_constructing_mock(self):
        config = MimoVADConfig(api_key="secret")
        with (
            patch(
                "animetta.services.vad.factory.ProviderRegistry.create_service",
                side_effect=RuntimeError("provider failed"),
            ),
            patch(
                "animetta.services.vad.factory.MockVAD",
                side_effect=AssertionError("MockVAD must not be constructed"),
            ),
            pytest.raises(RuntimeError, match="provider failed"),
        ):
            VADFactory.create_from_config(config, strict=True)


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
