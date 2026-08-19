from __future__ import annotations

import numpy as np

from scripts.train.prepare_data import analyze_audio


def test_audio_qc_resolves_sine_pitch_without_false_clipping() -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    audio = (0.2 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)

    metrics, flags = analyze_audio(
        audio,
        sample_rate,
        source_clipping_ratio=0.0,
        qc={
            "silence_threshold_dbfs": -45.0,
            "max_silence_ratio": 0.35,
            "max_clipping_ratio": 0.001,
            "min_snr_db": 18.0,
            "f0_min_hz": 50.0,
            "f0_max_hz": 1100.0,
            "min_duration_s": 0.5,
            "max_duration_s": 15.0,
        },
    )

    assert 215 <= float(metrics["f0_median_hz"]) <= 225
    assert "pitch_unresolved" not in flags
    assert "clipping" not in flags
