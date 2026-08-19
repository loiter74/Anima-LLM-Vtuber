from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.train.workspace import (
    MANIFEST_COLUMNS,
    build_rvc_plan,
    freeze_evaluation,
    freeze_split,
    validate_workspace,
)

SOURCE_COLUMNS = MANIFEST_COLUMNS["sources.csv"]
CLIP_COLUMNS = MANIFEST_COLUMNS["clips.csv"]


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "songs"
    (root / "manifests").mkdir(parents=True)
    (root / "project.toml").write_text(
        """
schema_version = 1
project_id = "character-cn-cover"
display_name = "待填写角色中文翻唱"

[data]
sample_rate = 48000
channels = 1
validation_ratio = 0.34
split_seed = "fixed-v1"

[baseline]
engine = "rvc"
version = "v2"
f0_method = "rmvpe"
epochs = 300
save_every_epochs = 25
batch_size = 4

[runtime]
rvc_root = "C:/RVC"
rvc_python = "C:/RVC/runtime/Scripts/python.exe"
gpu = "0"

[inference]
f0_up_key = 0
index_rate = 0.3
filter_radius = 5
rms_mix_rate = 0.5
protect = 0.5
""".strip()
        + "\n",
        encoding="utf-8",
    )
    _write_csv(root / "manifests" / "sources.csv", SOURCE_COLUMNS, [])
    _write_csv(root / "manifests" / "clips.csv", CLIP_COLUMNS, [])
    _write_csv(
        root / "manifests" / "evaluation_cases.csv",
        (
            "case_id",
            "range",
            "source_audio_relpath",
            "lyrics",
            "start_ms",
            "end_ms",
            "audio_sha256",
            "notes",
        ),
        [],
    )
    _write_csv(
        root / "manifests" / "versions.csv",
        (
            "version_id",
            "parent_version_id",
            "dataset_revision",
            "evaluation_revision",
            "model_sha256",
            "index_sha256",
            "config_relpath",
            "status",
            "notes",
        ),
        [],
    )
    _write_csv(
        root / "manifests" / "ab_reviews.csv",
        (
            "review_id",
            "case_id",
            "version_a",
            "version_b",
            "pitch_winner",
            "timbre_winner",
            "diction_winner",
            "stability_winner",
            "artifact_winner",
            "overall_winner",
            "reviewer",
            "notes",
        ),
        [],
    )
    _write_csv(
        root / "manifests" / "production_jobs.csv",
        (
            "job_id",
            "phrase_id",
            "input_relpath",
            "model_version",
            "pitch_shift",
            "output_relpath",
            "status",
            "issue",
            "notes",
        ),
        [],
    )
    return root


def _clip(clip_id: str, source_id: str) -> dict[str, str]:
    row = dict.fromkeys(CLIP_COLUMNS, "")
    row.update(
        {
            "clip_id": clip_id,
            "source_id": source_id,
            "audio_relpath": f"data/processed/{clip_id}.wav",
            "transcript": "测试台词",
            "duration_s": "5.0",
            "sample_rate": "48000",
            "channels": "1",
            "audio_sha256": (clip_id.encode("utf-8").hex() * 64)[:64],
            "review_status": "accepted",
            "reviewer": "reviewer",
        }
    )
    return row


def test_empty_repository_scaffold_is_valid_before_data_arrives(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    assert validate_workspace(root, stage="scaffold") == []


def test_split_is_frozen_by_source_before_augmentation(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    rows = [
        _clip("line-a-1", "line-a"),
        _clip("line-a-2", "line-a"),
        _clip("line-b-1", "line-b"),
        _clip("line-b-2", "line-b"),
        _clip("line-c-1", "line-c"),
        _clip("line-c-2", "line-c"),
    ]
    _write_csv(root / "manifests" / "clips.csv", CLIP_COLUMNS, rows)

    summary = freeze_split(root)

    with (root / "manifests" / "split.csv").open(encoding="utf-8", newline="") as handle:
        frozen = list(csv.DictReader(handle))
    by_source: dict[str, set[str]] = {}
    for row in frozen:
        by_source.setdefault(row["source_id"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in by_source.values())
    assert summary.validation_sources == 1
    assert summary.train_sources == 2
    with pytest.raises(FileExistsError, match="already exists"):
        freeze_split(root)


def test_rvc_plan_is_v2_rmvpe_and_never_auto_deploys(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    plan = build_rvc_plan(root, run_id="baseline-v001")

    assert [step.name for step in plan][-1] == "build-index"
    assert all(step.command[0] == "C:/RVC/runtime/Scripts/python.exe" for step in plan)
    flattened = " ".join(argument for step in plan for argument in step.command)
    assert "rmvpe" in flattened
    assert "deploy" not in flattened.lower()
    assert "baseline-v001" in flattened
    assert "f0G48k.pth" in flattened
    train = next(step for step in plan if step.name == "train")
    assert train.command[train.command.index("-sr") + 1] == "48k"
    preprocess = plan[0]
    assert preprocess.command[-2:] == ("False", "3.7")
    assert len([step for step in plan if step.name.startswith("extract-rmvpe-")]) == 4
    assert len([step for step in plan if step.name.startswith("extract-features-")]) == 4


def test_evaluation_revision_is_locked_to_low_mid_high_cases(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    rows = [
        {
            "case_id": f"case-{range_name}",
            "range": range_name,
            "source_audio_relpath": f"evaluation/audio/{range_name}.wav",
            "lyrics": "固定测试歌词",
            "start_ms": "0",
            "end_ms": "8000",
            "audio_sha256": range_name.encode().hex().ljust(64, "0")[:64],
            "notes": "",
        }
        for range_name in ("low", "mid", "high")
    ]
    _write_csv(
        root / "manifests" / "evaluation_cases.csv",
        (
            "case_id",
            "range",
            "source_audio_relpath",
            "lyrics",
            "start_ms",
            "end_ms",
            "audio_sha256",
            "notes",
        ),
        rows,
    )

    revision = freeze_evaluation(root)

    assert len(revision) == 64
    with pytest.raises(FileExistsError, match="already exists"):
        freeze_evaluation(root)
