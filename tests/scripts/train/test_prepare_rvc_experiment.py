from __future__ import annotations

from pathlib import Path

from scripts.train.prepare_rvc_experiment import prepare_experiment


def test_prepare_experiment_pins_config_and_complete_filelist(tmp_path: Path) -> None:
    root = tmp_path / "rvc"
    experiment = root / "logs" / "baseline-v001"
    for relative in ("0_gt_wavs", "3_feature768", "2a_f0", "2b-f0nsf"):
        (experiment / relative).mkdir(parents=True)
    config_source = root / "configs" / "v2" / "48k.json"
    config_source.parent.mkdir(parents=True)
    config_source.write_text('{"sample_rate": 48000}\n', encoding="utf-8")
    for name in ("line-1", "line-2"):
        (experiment / "0_gt_wavs" / f"{name}.wav").write_bytes(b"wav")
        (experiment / "3_feature768" / f"{name}.npy").write_bytes(b"feature")
        (experiment / "2a_f0" / f"{name}.wav.npy").write_bytes(b"coarse")
        (experiment / "2b-f0nsf" / f"{name}.wav.npy").write_bytes(b"f0")

    config, filelist = prepare_experiment(
        root,
        experiment="baseline-v001",
        sample_rate="48k",
        version="v2",
    )

    assert config.read_bytes() == config_source.read_bytes()
    assert len(filelist.read_text(encoding="utf-8").splitlines()) == 2
    prepare_experiment(root, experiment="baseline-v001", sample_rate="48k", version="v2")
