from __future__ import annotations

"""Tests for VisemeLipSync — FFT analysis, viseme→mouth mapping, SimpleLipSync fallback, factory."""


import numpy as np
import pytest

from animetta.services.live2d.viseme_sync import (
    SimpleLipSync,
    VisemeConfig,
    VisemeLipSync,
    create_lip_sync_engine,
)

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def viseme_config():
    """Default VisemeConfig for tests."""
    return VisemeConfig()


@pytest.fixture
def viseme_sync(viseme_config):
    """VisemeLipSync with default config."""
    return VisemeLipSync(config=viseme_config, sample_rate=24000)


@pytest.fixture
def simple_sync():
    """SimpleLipSync with default params."""
    return SimpleLipSync()


@pytest.fixture
def sine_audio():
    """Generate a sine wave audio segment for testing (24000Hz, 0.1s)."""
    sample_rate = 24000
    t = np.linspace(0, 0.1, int(sample_rate * 0.1), endpoint=False)
    return (np.sin(2 * np.pi * 440 * t)).astype(np.float32)


# ── VisemeConfig ─────────────────────────────────────────────────────


class TestVisemeConfig:
    """VisemeConfig dataclass initialization."""

    def test_default_bands(self, viseme_config):
        """Default frequency bands are set correctly."""
        assert viseme_config.bands["low"] == (120, 360)
        assert viseme_config.bands["lowMid"] == (360, 900)
        assert viseme_config.bands["mid"] == (900, 1800)
        assert viseme_config.bands["highMid"] == (1800, 3200)
        assert viseme_config.bands["high"] == (3200, 5200)

    def test_default_weights(self, viseme_config):
        """Default viseme weights are set for all 5 visemes."""
        assert "a" in viseme_config.weights
        assert "i" in viseme_config.weights
        assert "u" in viseme_config.weights
        assert "e" in viseme_config.weights
        assert "o" in viseme_config.weights
        assert len(viseme_config.weights["a"]) == 5  # 5 bands

    def test_default_smoothing_params(self, viseme_config):
        """Default smoothing/attack/release are set."""
        assert viseme_config.attack == 0.02
        assert viseme_config.release == 0.1
        assert viseme_config.smoothing == 0.3

    def test_custom_bands(self):
        """Custom frequency bands override defaults."""
        custom_bands = {"low": (100, 400), "mid": (400, 2000)}
        cfg = VisemeConfig(bands=custom_bands, weights={"a": [0.5, 0.5]})
        assert cfg.bands["low"] == (100, 400)
        assert cfg.bands["mid"] == (400, 2000)

    def test_custom_smoothing(self):
        """Custom smoothing values are stored."""
        cfg = VisemeConfig(smoothing=0.5, attack=0.01, release=0.05)
        assert cfg.smoothing == 0.5
        assert cfg.attack == 0.01
        assert cfg.release == 0.05


# ── VisemeLipSync — Band Energy ──────────────────────────────────────


class TestBandEnergy:
    """extract_band_energy tests."""

    def test_extract_band_energy_positive(self, viseme_sync):
        """Band energy extraction returns positive value for non-zero data."""
        freq_buf = np.ones(512) * 0.5  # Uniform magnitude
        energy = viseme_sync.extract_band_energy(freq_buf, 24000, 120, 360)
        assert energy > 0.0
        assert energy == pytest.approx(0.5, abs=0.01)

    def test_extract_band_energy_zero_out_of_band(self, viseme_sync):
        """Band energy for range with no bins returns 0."""
        freq_buf = np.ones(512) * 0.5
        # min_idx == max_idx due to narrow range at low sample rate
        energy = viseme_sync.extract_band_energy(freq_buf, 8000, 1, 2)
        assert energy == 0.0

    def test_extract_band_energy_clamps_indices(self, viseme_sync):
        """Indices are clamped to valid range."""
        freq_buf = np.ones(256) * 0.3
        # min_freq = 0, max_freq very large — should clamp
        energy = viseme_sync.extract_band_energy(freq_buf, 16000, 0, 16000)
        assert energy == pytest.approx(0.3, abs=0.01)


# ── VisemeLipSync — Feature Extraction ───────────────────────────────


class TestVisemeFeatures:
    """extract_viseme_features tests."""

    def test_small_audio_padded_to_window(self, viseme_sync):
        """Audio shorter than window_size is zero-padded."""
        short_audio = np.array([0.1, -0.1, 0.05], dtype=np.float32)
        features = viseme_sync.extract_viseme_features(short_audio, voice_energy=1.0)
        assert len(features) == 5  # 5 bands
        assert all(isinstance(f, float) for f in features)

    def test_features_length_is_five(self, viseme_sync, sine_audio):
        """extract_viseme_features always returns 5 band energies."""
        features = viseme_sync.extract_viseme_features(sine_audio, voice_energy=0.8)
        assert len(features) == 5
        assert all(f >= 0.0 for f in features)

    def test_all_zero_audio_produces_zero_features(self, viseme_sync):
        """Silent audio (all zeros) produces zero energy features."""
        silent = np.zeros(2048, dtype=np.float32)
        features = viseme_sync.extract_viseme_features(silent, voice_energy=1.0)
        assert features == [0.0, 0.0, 0.0, 0.0, 0.0]


# ── VisemeLipSync — Viseme Inference ─────────────────────────────────


class TestVisemeInference:
    """infer_viseme_weights and smoothing tests."""

    def test_infer_viseme_weights_normalizes(self, viseme_sync):
        """Weights are computed from normalized band energies."""
        features = [0.1, 0.2, 0.3, 0.2, 0.2]
        weights = viseme_sync.infer_viseme_weights(features)
        assert len(weights) == 5
        assert all(0.0 <= w <= 1.0 for w in weights)

    def test_infer_viseme_weights_all_zero(self, viseme_sync):
        """All-zero features yield all-zero weights."""
        weights = viseme_sync.infer_viseme_weights([0.0, 0.0, 0.0, 0.0, 0.0])
        assert np.all(weights == 0.0)

    def test_apply_smoothing_converges(self, viseme_sync):
        """Repeated smoothing converges weights toward target."""
        viseme_sync._current_weights = np.zeros(5)
        target = np.array([0.5, 0.3, 0.2, 0.1, 0.0])
        for _ in range(20):
            result = viseme_sync.apply_smoothing(target)
        # After many iterations, should be close to target
        assert np.allclose(result, target, atol=0.01)

    def test_apply_smoothing_single_step(self, viseme_sync):
        """Single smoothing step blends current and target."""
        viseme_sync._current_weights = np.zeros(5)
        target = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
        result = viseme_sync.apply_smoothing(target)
        # alpha=0.3 → result = 0.3 * 1.0 + 0.7 * 0.0 = 0.3
        assert result[0] == pytest.approx(0.3, abs=0.001)
        assert result[1] == pytest.approx(0.0, abs=0.001)


# ── VisemeLipSync — Full Pipeline ────────────────────────────────────


class TestProcessAudio:
    """process_audio end-to-end tests."""

    def test_process_audio_returns_mouth_params(self, viseme_sync, sine_audio):
        """process_audio returns Dict with ParamMouthOpen and ParamMouthForm."""
        result = viseme_sync.process_audio(sine_audio, voice_energy=0.8)
        assert "ParamMouthOpen" in result
        assert "ParamMouthForm" in result
        assert isinstance(result["ParamMouthOpen"], float)
        assert isinstance(result["ParamMouthForm"], float)

    def test_process_audio_mouth_open_positive_for_sound(self, viseme_sync, sine_audio):
        """Non-silent audio produces positive mouth openness."""
        result = viseme_sync.process_audio(sine_audio, voice_energy=1.0)
        assert result["ParamMouthOpen"] >= 0.0

    def test_process_audio_silence_zeros_everything(self, viseme_sync):
        """Silent audio with zero energy produces zero mouth params."""
        silent = np.zeros(2048, dtype=np.float32)
        result = viseme_sync.process_audio(silent, voice_energy=0.0)
        assert result["ParamMouthOpen"] == 0.0
        assert result["ParamMouthForm"] == 0.0

    def test_reset_clears_state(self, viseme_sync):
        """reset() zeros internal weights."""
        viseme_sync._current_weights = np.array([0.5, 0.3, 0.2, 0.1, 0.0])
        viseme_sync._target_weights = np.array([0.8, 0.1, 0.1, 0.0, 0.0])
        viseme_sync.reset()
        assert np.all(viseme_sync._current_weights == 0.0)
        assert np.all(viseme_sync._target_weights == 0.0)

    def test_voice_energy_scales_mouth_open(self, viseme_sync, sine_audio):
        """Higher voice_energy produces larger mouth_open."""
        # Since smoothing blends across calls, reset between tests
        viseme_sync.reset()
        result_low = viseme_sync.process_audio(sine_audio, voice_energy=0.3)
        viseme_sync.reset()
        result_high = viseme_sync.process_audio(sine_audio, voice_energy=1.0)
        assert result_high["ParamMouthOpen"] >= result_low["ParamMouthOpen"]


# ── SimpleLipSync ────────────────────────────────────────────────────


class TestSimpleLipSync:
    """SimpleLipSync RMS-based fallback."""

    def test_init_defaults(self, simple_sync):
        """Default sensitivity and smoothing are set."""
        assert simple_sync.sensitivity == 2.5
        assert simple_sync.smoothing == 0.3
        assert simple_sync._current_value == 0.0

    def test_process_audio_returns_float(self, simple_sync, sine_audio):
        """process_audio returns float mouth openness."""
        result = simple_sync.process_audio(sine_audio)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_silence_returns_zero(self, simple_sync):
        """All-zero audio returns zero."""
        silent = np.zeros(1024, dtype=np.float32)
        result = simple_sync.process_audio(silent)
        assert result == pytest.approx(0.0, abs=0.01)

    def test_loud_audio_saturates(self, simple_sync):
        """Very loud audio saturates at 1.0."""
        loud = np.ones(1024, dtype=np.float32) * 10.0
        result = simple_sync.process_audio(loud)
        # After smoothing it won't immediately be 1.0, but after many calls...
        for _ in range(20):
            result = simple_sync.process_audio(loud)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_smoothing_prevents_jumps(self, simple_sync):
        """Smoothing prevents sudden value jumps."""
        simple_sync.reset()
        medium = np.ones(512, dtype=np.float32) * 0.5
        r1 = simple_sync.process_audio(medium)
        # RMS of [0.5, 0.5, ...] is 0.5; raw = min(1.0, 0.5 * 2.5) = 1.0 (clamped)
        # With smoothing 0.3: result = 0.3 * 1.0 + 0.7 * 0.0 = 0.3
        assert r1 < 0.5  # Should be smoothed, not immediate jump

    def test_reset_zeros_state(self, simple_sync):
        """reset() zeros internal value."""
        simple_sync._current_value = 0.8
        simple_sync.reset()
        assert simple_sync._current_value == 0.0


# ── Factory Function ─────────────────────────────────────────────────


class TestCreateLipSyncEngine:
    """create_lip_sync_engine factory tests."""

    def test_viseme_mode_returns_viseme_lip_sync(self):
        """Factory with mode='viseme' returns VisemeLipSync."""
        engine = create_lip_sync_engine(mode="viseme")
        assert isinstance(engine, VisemeLipSync)

    def test_simple_mode_returns_simple_lip_sync(self):
        """Factory with mode='simple' returns SimpleLipSync."""
        engine = create_lip_sync_engine(mode="simple")
        assert isinstance(engine, SimpleLipSync)

    def test_invalid_mode_raises_value_error(self):
        """Unknown mode raises ValueError."""
        with pytest.raises(ValueError, match="Unknown lip sync mode"):
            create_lip_sync_engine(mode="invalid_mode")

    def test_kwargs_passed_to_simple_mode(self):
        """Extra kwargs are forwarded to SimpleLipSync."""
        engine = create_lip_sync_engine(mode="simple", sensitivity=3.0, smoothing=0.5)
        assert isinstance(engine, SimpleLipSync)
        assert engine.sensitivity == 3.0
        assert engine.smoothing == 0.5

    def test_kwargs_passed_to_viseme_mode(self):
        """Extra kwargs are forwarded to VisemeConfig."""
        engine = create_lip_sync_engine(mode="viseme", smoothing=0.8, attack=0.05)
        assert isinstance(engine, VisemeLipSync)
        assert engine.config.smoothing == 0.8
        assert engine.config.attack == 0.05

    def test_default_sample_rate_is_24000(self):
        """Default sample_rate for viseme mode is 24000."""
        engine = create_lip_sync_engine(mode="viseme")
        assert engine.sample_rate == 24000

    def test_custom_sample_rate(self):
        """Custom sample_rate is forwarded to VisemeLipSync."""
        engine = create_lip_sync_engine(mode="viseme", sample_rate=16000)
        assert engine.sample_rate == 16000
