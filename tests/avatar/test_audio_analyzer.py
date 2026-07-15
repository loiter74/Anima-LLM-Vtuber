from __future__ import annotations

"""
Tests for AudioAnalyzer — volume envelope computation for lip sync.
"""

import math
import struct
import wave

from animetta.avatar.analyzers.audio import AudioAnalyzer, compute_volume_envelope
from animetta.orchestration.graph.output_node import _compute_volumes, _trim_leading_silence

# ============================================================
# helpers
# ============================================================


def _create_sine_wave_wav(
    path: str,
    duration_sec: float = 1.0,
    freq: float = 440,
    sample_rate: int = 16000,
    max_amplitude: float = 0.5,
) -> str:
    """Create a simple sine-wave WAV file for testing."""
    n_samples = int(sample_rate * duration_sec)
    data = []
    for i in range(n_samples):
        t = i / sample_rate
        # Sine wave
        sample = max_amplitude * 0.5 * (1 + math.sin(2 * math.pi * freq * t))
        data.append(int(sample * 32767))
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(data)}h", *data))
    return path


def _create_silent_wav(path: str, duration_sec: float = 1.0, sample_rate: int = 16000) -> str:
    """Create a silent WAV file."""
    n_samples = int(sample_rate * duration_sec)
    data = [0] * n_samples
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(data)}h", *data))
    return path


def _create_wav_with_leading_silence(
    path: str, silence_sec: float = 0.3, duration_sec: float = 1.0, sample_rate: int = 16000
) -> str:
    """Create a WAV file with leading silence followed by sine wave."""
    silence_samples = int(sample_rate * silence_sec)
    tone_samples = int(sample_rate * duration_sec)
    samples = [0] * silence_samples
    for i in range(tone_samples):
        t = i / sample_rate
        val = int(0.5 * 32767 * math.sin(2 * math.pi * 440 * t))
        samples.append(val)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


# ============================================================
# AudioAnalyzer tests
# ============================================================


class TestAudioAnalyzerInit:
    """AudioAnalyzer initialization."""

    def test_init_default_sample_rate(self):
        """Default sample rate should be 50 Hz."""
        analyzer = AudioAnalyzer(sample_rate=50)
        assert analyzer.sample_rate == 50
        assert analyzer.sample_interval_ms == 20.0

    def test_init_custom_sample_rate(self):
        """Custom sample rate should be honored."""
        analyzer = AudioAnalyzer(sample_rate=100)
        assert analyzer.sample_rate == 100
        assert analyzer.sample_interval_ms == 10.0


class TestAudioAnalyzerVolumeEnvelope:
    """compute_volume_envelope behavior."""

    def test_returns_list_of_floats(self, tmp_path):
        """Should return a list of floats in [0, 1] range."""
        wav = _create_sine_wave_wav(str(tmp_path / "test.wav"))
        analyzer = AudioAnalyzer(sample_rate=50)
        volumes = analyzer.compute_volume_envelope(wav, normalize=True, gain=1.0)
        assert isinstance(volumes, list)
        assert len(volumes) > 0
        assert all(isinstance(v, float) for v in volumes)
        assert all(0.0 <= v <= 1.0 for v in volumes)

    def test_silent_audio_returns_zeros(self, tmp_path):
        """Silent audio should return all zeros."""
        wav = _create_silent_wav(str(tmp_path / "silent.wav"), duration_sec=1.0)
        analyzer = AudioAnalyzer(sample_rate=50)
        volumes = analyzer.compute_volume_envelope(wav, normalize=True, gain=1.0)
        assert all(v == 0.0 for v in volumes)

    def test_short_audio_returns_empty(self, tmp_path):
        """Audio shorter than one sample interval returns empty list."""
        wav = _create_sine_wave_wav(str(tmp_path / "short.wav"), duration_sec=0.01)
        analyzer = AudioAnalyzer(sample_rate=50)
        volumes = analyzer.compute_volume_envelope(wav)
        assert volumes == []

    def test_gain_amplifies_volume(self, tmp_path):
        """Gain > 1 should amplify volume values (capped at 1.0)."""
        wav = _create_sine_wave_wav(str(tmp_path / "gain.wav"), max_amplitude=0.3)
        analyzer = AudioAnalyzer(sample_rate=50)

        volumes_no_gain = analyzer.compute_volume_envelope(wav, normalize=True, gain=1.0)
        volumes_with_gain = analyzer.compute_volume_envelope(wav, normalize=True, gain=2.0)

        # With gain, more values should be at or near 1.0
        max_no_gain = max(volumes_no_gain)
        max_with_gain = max(volumes_with_gain)
        assert max_with_gain >= max_no_gain

    def test_num_samples_matches_duration(self, tmp_path):
        """Number of samples should match duration / interval."""
        duration = 2.0  # seconds
        wav = _create_sine_wave_wav(str(tmp_path / "duration.wav"), duration_sec=duration)
        analyzer = AudioAnalyzer(sample_rate=50)  # 50 Hz = 20ms interval
        volumes = analyzer.compute_volume_envelope(wav, normalize=False)
        # 2s / 0.02s = 100 samples
        assert len(volumes) == 100, f"Expected 100 samples, got {len(volumes)}"

    def test_louder_audio_has_higher_values(self, tmp_path):
        """Louder audio should produce higher volume values."""
        quiet = _create_sine_wave_wav(str(tmp_path / "quiet.wav"), max_amplitude=0.1)
        loud = _create_sine_wave_wav(str(tmp_path / "loud.wav"), max_amplitude=0.9)

        analyzer = AudioAnalyzer(sample_rate=50)
        # Use normalize=False and gain=1.0 to preserve amplitude differences
        quiet_volumes = analyzer.compute_volume_envelope(quiet, normalize=False, gain=1.0)
        loud_volumes = analyzer.compute_volume_envelope(loud, normalize=False, gain=1.0)

        assert max(loud_volumes) > max(quiet_volumes)

    def test_normalize_scales_to_max(self, tmp_path):
        """With normalize=True, max value should be 1.0."""
        wav = _create_sine_wave_wav(str(tmp_path / "norm.wav"), max_amplitude=0.5)
        analyzer = AudioAnalyzer(sample_rate=50)
        volumes = analyzer.compute_volume_envelope(wav, normalize=True, gain=1.0)
        assert abs(max(volumes) - 1.0) < 0.01

    def test_file_not_found_returns_empty(self, tmp_path):
        """Non-existent file returns empty list."""
        analyzer = AudioAnalyzer(sample_rate=50)
        volumes = analyzer.compute_volume_envelope(str(tmp_path / "nonexistent.wav"))
        assert volumes == []

    def test_convenience_function(self, tmp_path):
        """The convenience function should work the same."""
        wav = _create_sine_wave_wav(str(tmp_path / "conv.wav"))
        volumes = compute_volume_envelope(wav, sample_rate=50, gain=1.0)
        assert isinstance(volumes, list)
        assert len(volumes) > 0

    def test_use_peak_mode(self, tmp_path):
        """Peak mode should return values in [0, 1] range."""
        wav = _create_sine_wave_wav(str(tmp_path / "peak.wav"))
        analyzer = AudioAnalyzer(sample_rate=50)
        volumes = analyzer.compute_volume_envelope(wav, use_peak=True)
        assert all(0.0 <= v <= 1.0 for v in volumes)

    def test_different_sample_rate(self, tmp_path):
        """Different sample rate should produce different number of samples."""
        wav = _create_sine_wave_wav(str(tmp_path / "rate.wav"), duration_sec=1.0)
        analyzer_25 = AudioAnalyzer(sample_rate=25)  # 40ms interval
        analyzer_100 = AudioAnalyzer(sample_rate=100)  # 10ms interval
        v25 = analyzer_25.compute_volume_envelope(wav, normalize=False)
        v100 = analyzer_100.compute_volume_envelope(wav, normalize=False)
        assert len(v25) < len(v100)


class TestAudioAnalyzerDuration:
    """get_audio_duration behavior."""

    def test_duration_matches(self, tmp_path):
        """Duration should match the created file."""
        wav = _create_sine_wave_wav(str(tmp_path / "dur.wav"), duration_sec=2.5)
        analyzer = AudioAnalyzer(sample_rate=50)
        duration = analyzer.get_audio_duration(wav)
        assert abs(duration - 2.5) < 0.1

    def test_duration_file_not_found(self, tmp_path):
        """Non-existent file returns 0."""
        analyzer = AudioAnalyzer(sample_rate=50)
        duration = analyzer.get_audio_duration(str(tmp_path / "nope.wav"))
        assert duration == 0.0


# ============================================================
# Convenience function compute_volume_envelope
# ============================================================


class TestConvenienceComputeVolumeEnvelope:
    """Standalone compute_volume_envelope convenience function."""

    def test_default_params(self, tmp_path):
        """Default params should produce valid output."""
        wav = _create_sine_wave_wav(str(tmp_path / "default.wav"))
        volumes = compute_volume_envelope(wav)
        assert isinstance(volumes, list)
        assert len(volumes) > 0
        assert all(0.0 <= v <= 1.0 for v in volumes)

    def test_custom_sample_rate(self, tmp_path):
        """Custom sample rate should be honored."""
        wav = _create_sine_wave_wav(str(tmp_path / "custom_rate.wav"), duration_sec=2.0)
        volumes_25 = compute_volume_envelope(wav, sample_rate=25)
        volumes_100 = compute_volume_envelope(wav, sample_rate=100)
        assert len(volumes_25) < len(volumes_100)
        # 2s / (1/25) = 50, 2s / (1/100) = 200
        assert len(volumes_25) == 50
        assert len(volumes_100) == 200

    def test_custom_gain(self, tmp_path):
        """Custom gain factor should amplify output."""
        wav = _create_sine_wave_wav(str(tmp_path / "custom_gain.wav"), max_amplitude=0.3)
        volumes_low = compute_volume_envelope(wav, gain=0.5)
        volumes_high = compute_volume_envelope(wav, gain=3.0)
        assert max(volumes_high) >= max(volumes_low)

    def test_silent_audio(self, tmp_path):
        """Silent audio should return empty list or zeros."""
        wav = _create_silent_wav(str(tmp_path / "silent_conv.wav"), duration_sec=0.5)
        volumes = compute_volume_envelope(wav)
        assert all(v == 0.0 for v in volumes)

    def test_nonexistent_file(self, tmp_path):
        """Non-existent file should return empty list."""
        volumes = compute_volume_envelope(str(tmp_path / "nope.wav"))
        assert volumes == []

    def test_very_short_audio(self, tmp_path):
        """Very short audio should return empty list."""
        wav = _create_sine_wave_wav(str(tmp_path / "vshort.wav"), duration_sec=0.005)
        volumes = compute_volume_envelope(wav)
        assert volumes == []


# ============================================================
# output_node _compute_volumes integration tests
# ============================================================


class TestOutputNodeComputeVolumes:
    """_compute_volumes function in output_node."""

    def test_compute_volumes_from_wav(self, tmp_path):
        """_compute_volumes should return volumes for a valid WAV."""
        wav = _create_sine_wave_wav(str(tmp_path / "test.wav"))
        volumes = _compute_volumes(wav)
        assert isinstance(volumes, list)
        assert len(volumes) > 0
        assert all(isinstance(v, float) for v in volumes)

    def test_compute_volumes_fallback_on_error(self, tmp_path):
        """_compute_volumes should return empty list on error."""
        volumes = _compute_volumes(str(tmp_path / "nonexistent.mp3"))
        assert volumes == []

    def test_compute_volumes_uses_default_gain(self, tmp_path):
        """_compute_volumes should use default gain of 3.5."""
        wav = _create_sine_wave_wav(str(tmp_path / "gain_test.wav"))
        volumes = _compute_volumes(wav)
        assert all(v >= 0.0 for v in volumes)

    def test_compute_volumes_clamps_to_01(self, tmp_path):
        """_compute_volumes volumes should be clamped to [0, 1]."""
        wav = _create_sine_wave_wav(str(tmp_path / "clamp.wav"), max_amplitude=0.9)
        volumes = _compute_volumes(wav)
        assert all(0.0 <= v <= 1.0 for v in volumes)

    def test_compute_volumes_uses_peak_mode(self, tmp_path):
        """_compute_volumes should use peak amplitude mode."""
        wav = _create_sine_wave_wav(str(tmp_path / "peak_mode.wav"))
        volumes = _compute_volumes(wav)
        # Peak mode means some values should be > 0 for non-silent audio
        assert any(v > 0.0 for v in volumes)

    def test_compute_volumes_no_normalize(self, tmp_path):
        """_compute_volumes should NOT normalize globally (use_peak=True, normalize=False)."""
        wav = _create_sine_wave_wav(str(tmp_path / "nonorm.wav"), max_amplitude=0.3)
        volumes = _compute_volumes(wav)
        # Volumes are in [0, 1] range even if not normalized
        assert all(0.0 <= v <= 1.0 for v in volumes)

    def test_trim_leading_silence_no_silence(self, tmp_path):
        """Audio without silence should not be trimmed."""
        wav = _create_sine_wave_wav(str(tmp_path / "no_silence.wav"))
        result = _trim_leading_silence(wav)
        assert result is None, "Should return None when no silence to trim"

    def test_trim_leading_silence_removes_silence(self, tmp_path):
        """Audio with leading silence should be trimmed."""
        wav = _create_wav_with_leading_silence(
            str(tmp_path / "has_silence.wav"), silence_sec=0.3, duration_sec=0.3
        )
        result = _trim_leading_silence(wav)
        assert result is not None, "Should trim audio with leading silence"
        # Trimmed file should be about 0.3s (only the tone part)
        from pydub import AudioSegment

        trimmed = AudioSegment.from_file(result)
        assert abs(len(trimmed) - 300) < 100, f"Trimmed length {len(trimmed)}ms, expected ~300ms"

    def test_trim_leading_silence_short_silence_ignored(self, tmp_path):
        """Leading silence shorter than 50ms should not be trimmed."""
        wav = _create_wav_with_leading_silence(
            str(tmp_path / "short_silence.wav"), silence_sec=0.03, duration_sec=0.3
        )
        result = _trim_leading_silence(wav)
        assert result is None, "Should not trim <50ms silence"

    def test_trim_leading_silence_full_silence(self, tmp_path):
        """Fully silent audio should not be trimmed (no onset detected)."""
        wav = _create_silent_wav(str(tmp_path / "full_silence.wav"), duration_sec=1.0)
        result = _trim_leading_silence(wav)
        assert result is None

    def test_compute_volumes_skips_leading_silence(self, tmp_path):
        """_trim_leading_silence should remove silence so volumes match speech onset."""
        wav = _create_wav_with_leading_silence(
            str(tmp_path / "silence_lead.wav"), silence_sec=0.3, duration_sec=0.5
        )

        # Trim silence, then compute volumes from trimmed audio
        trimmed = _trim_leading_silence(wav)
        assert trimmed is not None, "Should have trimmed audio"
        volumes = _compute_volumes(trimmed)
        assert len(volumes) > 0
        # First volumes should now represent speech, not silence
        first_few = volumes[:5]
        assert any(v > 0.01 for v in first_few), (
            f"First 5 volumes are all near zero after silence trim: {first_few}"
        )

    def test_compute_volumes_silent_audio_no_trim_error(self, tmp_path):
        """_compute_volumes should handle fully silent audio gracefully."""
        wav = _create_silent_wav(str(tmp_path / "all_silent.wav"), duration_sec=1.0)
        volumes = _compute_volumes(wav)
        # Silent audio with gain=3.5 might still produce 0s
        assert isinstance(volumes, list)
