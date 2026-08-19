"""Create a pinned RVC config and file list after feature extraction."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path


def _replace_if_same_or_missing(source: Path, destination: Path) -> None:
    content = source.read_bytes()
    if destination.exists():
        if destination.read_bytes() != content:
            raise FileExistsError(f"Existing file differs: {destination}")
        return
    destination.write_bytes(content)


def prepare_experiment(
    rvc_root: Path,
    *,
    experiment: str,
    sample_rate: str,
    version: str,
) -> tuple[Path, Path]:
    experiment_dir = rvc_root / "logs" / experiment
    wav_dir = experiment_dir / "0_gt_wavs"
    feature_dir = experiment_dir / ("3_feature768" if version == "v2" else "3_feature256")
    coarse_f0_dir = experiment_dir / "2a_f0"
    f0_dir = experiment_dir / "2b-f0nsf"
    config_source = rvc_root / "configs" / version / f"{sample_rate}.json"
    for path in (wav_dir, feature_dir, coarse_f0_dir, f0_dir):
        if not path.is_dir():
            raise FileNotFoundError(f"RVC extraction directory missing: {path}")
    if not config_source.is_file():
        raise FileNotFoundError(f"RVC config missing: {config_source}")

    names = sorted(path.stem for path in wav_dir.glob("*.wav"))
    lines: list[str] = []
    missing: list[str] = []
    for name in names:
        wav = wav_dir / f"{name}.wav"
        feature = feature_dir / f"{name}.npy"
        coarse_f0 = coarse_f0_dir / f"{name}.wav.npy"
        f0 = f0_dir / f"{name}.wav.npy"
        absent = [path for path in (feature, coarse_f0, f0) if not path.is_file()]
        if absent:
            missing.extend(str(path) for path in absent)
            continue
        lines.append("|".join((str(wav), str(feature), str(coarse_f0), str(f0), "0")))
    if not lines:
        raise ValueError("No complete RVC training examples were extracted")
    if missing:
        raise ValueError(f"Incomplete RVC extraction; first missing file: {missing[0]}")

    config_path = experiment_dir / "config.json"
    _replace_if_same_or_missing(config_source, config_path)
    filelist_path = experiment_dir / "filelist.txt"
    payload = "\n".join(lines) + "\n"
    if filelist_path.exists() and filelist_path.read_text(encoding="utf-8") != payload:
        raise FileExistsError(f"Existing file differs: {filelist_path}")
    filelist_path.write_text(payload, encoding="utf-8")
    return config_path, filelist_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare an RVC experiment directory")
    parser.add_argument("--rvc-root", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--sample-rate", choices=("32k", "40k", "48k"), required=True)
    parser.add_argument("--version", choices=("v1", "v2"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config, filelist = prepare_experiment(
        args.rvc_root.resolve(),
        experiment=args.experiment,
        sample_rate=args.sample_rate,
        version=args.version,
    )
    print(f"Prepared RVC config: {config}")
    print(f"Prepared RVC file list: {filelist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
