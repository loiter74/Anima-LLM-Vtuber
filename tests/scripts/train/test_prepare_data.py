from __future__ import annotations

import numpy as np
import soundfile as sf

from scripts.train.prepare_data import _process_sources, analyze_audio


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


def test_process_sources_supports_bounded_parallel_workers(tmp_path) -> None:
    sample_rate = 8_000
    raw_dir = tmp_path / "audio" / "raw"
    raw_dir.mkdir(parents=True)
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    rows = []
    for index, frequency in enumerate((220, 330), start=1):
        source_id = f"sample-{index}"
        path = raw_dir / f"{source_id}.wav"
        sf.write(path, 0.2 * np.sin(2 * np.pi * frequency * time), sample_rate)
        rows.append(
            {
                "source_id": source_id,
                "audio_relpath": path.relative_to(tmp_path).as_posix(),
                "transcript": f"样本{index}",
            }
        )

    processed, failures = _process_sources(
        tmp_path,
        rows,
        project={
            "data": {
                "sample_rate": sample_rate,
                "min_duration_s": 0.5,
                "max_duration_s": 15.0,
            },
            "qc": {
                "silence_threshold_dbfs": -45.0,
                "max_silence_ratio": 0.35,
                "max_clipping_ratio": 0.001,
                "min_snr_db": 18.0,
                "f0_min_hz": 50.0,
                "f0_max_hz": 1_100.0,
            },
        },
        existing={},
        workers=2,
    )

    assert failures == []
    assert [row["clip_id"] for row in processed] == ["sample-1", "sample-2"]
    assert all((tmp_path / row["audio_relpath"]).is_file() for row in processed)
