"""按冻结清单物化 RVC 的 train/validation 音频目录。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from scripts.train.workspace import validate_workspace


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def materialize(root: Path) -> dict[str, int | str]:
    errors = validate_workspace(root, stage="dataset")
    if errors:
        raise ValueError("数据集未就绪：" + "; ".join(errors))
    clips = {row["clip_id"]: row for row in _read(root / "manifests" / "clips.csv")}
    split = _read(root / "manifests" / "split.csv")
    expected_destinations: set[Path] = set()
    counts = {"train": 0, "validation": 0}
    for assignment in split:
        clip = clips[assignment["clip_id"]]
        source = (root / clip["audio_relpath"]).resolve()
        try:
            source.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"片段路径越出工作区：{clip['audio_relpath']}") from error
        if not source.is_file() or _sha256(source) != assignment["audio_sha256"].lower():
            raise ValueError(f"片段缺失或哈希变化：{assignment['clip_id']}")
        destination = (
            root / "audio" / "dataset" / assignment["split"] / f"{assignment['clip_id']}.wav"
        )
        expected_destinations.add(destination.resolve())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and _sha256(destination) != assignment["audio_sha256"].lower():
            raise FileExistsError(f"目标已存在但内容不同：{destination}")
        if not destination.exists():
            shutil.copy2(source, destination)
        counts[assignment["split"]] += 1

    for directory in (
        root / "audio" / "dataset" / "train",
        root / "audio" / "dataset" / "validation",
    ):
        stale = [
            path for path in directory.glob("*.wav") if path.resolve() not in expected_destinations
        ]
        if stale:
            raise FileExistsError(f"发现不属于当前 revision 的旧片段：{stale[0]}")
    revision = split[0]["dataset_revision"]
    lock: dict[str, int | str] = {
        "schema_version": 1,
        "dataset_revision": revision,
        "train_clips": counts["train"],
        "validation_clips": counts["validation"],
    }
    (root / "manifests" / "dataset.lock.json").write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return lock


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="物化冻结的 RVC 数据集")
    parser.add_argument("--project", type=Path, default=Path("songs"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = materialize(args.project.resolve())
    except (KeyError, OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
