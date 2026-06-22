"""Tests for Live2D lip sync engines."""

from __future__ import annotations

import numpy as np
import pytest

from animetta.services.live2d.viseme_sync import (
    SimpleLipSync,
    VisemeLipSync,
    create_lip_sync_engine,
)


class TestCreateLipSyncEngine:
    def test_create_viseme_engine(self):
        engine = create_lip_sync_engine("viseme", sample_rate=24000)
        assert isinstance(engine, VisemeLipSync)
        assert engine.sample_rate == 24000

    def test_create_simple_engine(self):
        engine = create_lip_sync_engine("simple", sensitivity=2.0)
        assert isinstance(engine, SimpleLipSync)
        assert engine.sensitivity == 2.0

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown lip sync mode"):
            create_lip_sync_engine("unknown")


class TestSimpleLipSync:
    def test_process_audio_returns_normalized_value(self):
        engine = SimpleLipSync(sensitivity=2.0, smoothing=1.0)
        audio = np.array([0.0, 0.5, -0.5], dtype=float)

        value = engine.process_audio(audio)

        assert 0.0 <= value <= 1.0

    def test_reset_clears_current_value(self):
        engine = SimpleLipSync(smoothing=1.0)
        engine.process_audio(np.array([1.0, -1.0], dtype=float))

        engine.reset()

        assert engine._current_value == 0.0
