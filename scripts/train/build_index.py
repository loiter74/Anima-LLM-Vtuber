"""Build a deterministic FAISS index from one RVC experiment."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from pathlib import Path

import faiss
import numpy as np


def build_index(rvc_root: Path, *, experiment: str, version: str) -> Path:
    experiment_dir = rvc_root / "logs" / experiment
    dimensions = 768 if version == "v2" else 256
    feature_dir = experiment_dir / f"3_feature{dimensions}"
    feature_paths = sorted(feature_dir.glob("*.npy"))
    if not feature_paths:
        raise FileNotFoundError(f"No RVC features found: {feature_dir}")
    arrays: list[np.ndarray] = []
    for path in feature_paths:
        feature = np.load(path)
        if feature.ndim != 2 or feature.shape[1] != dimensions:
            raise ValueError(f"Unexpected feature shape {feature.shape}: {path}")
        arrays.append(np.asarray(feature, dtype=np.float32))
    features = np.concatenate(arrays, axis=0)
    if features.shape[0] < 39:
        raise ValueError("At least 39 feature frames are required to build an IVF index")
    rng = np.random.default_rng(0)
    features = features[rng.permutation(features.shape[0])]
    total_feature_path = experiment_dir / "total_fea.npy"
    np.save(total_feature_path, features)

    n_ivf = max(1, min(int(16 * math.sqrt(features.shape[0])), features.shape[0] // 39))
    index = faiss.index_factory(dimensions, f"IVF{n_ivf},Flat")
    training_features = features
    if len(features) > 200_000:
        selection = rng.choice(len(features), size=200_000, replace=False)
        training_features = features[selection]
    index.train(training_features)
    index_ivf = faiss.extract_index_ivf(index)
    index_ivf.nprobe = 1

    trained = experiment_dir / f"trained_IVF{n_ivf}_Flat_{experiment}_{version}.index"
    added = experiment_dir / f"added_IVF{n_ivf}_Flat_nprobe_1_{experiment}_{version}.index"
    faiss.write_index(index, str(trained))
    for start in range(0, len(features), 8192):
        index.add(features[start : start + 8192])
    faiss.write_index(index, str(added))
    receipt = {
        "schema_version": 1,
        "experiment": experiment,
        "version": version,
        "dimensions": dimensions,
        "feature_frames": int(features.shape[0]),
        "n_ivf": n_ivf,
        "nprobe": 1,
        "trained_index": trained.name,
        "added_index": added.name,
    }
    (experiment_dir / "index.receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return added


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an RVC FAISS index")
    parser.add_argument("--rvc-root", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--version", choices=("v1", "v2"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    index = build_index(
        args.rvc_root.resolve(),
        experiment=args.experiment,
        version=args.version,
    )
    print(f"Built RVC index: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
