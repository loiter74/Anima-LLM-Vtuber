"""角色翻唱工作区的清单校验、固定划分与 RVC 训练计划。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MANIFEST_COLUMNS: dict[str, tuple[str, ...]] = {
    "sources.csv": (
        "source_id",
        "audio_relpath",
        "transcript",
        "source_reference",
        "usage_rights",
        "speaker",
        "scene",
        "notes",
    ),
    "clips.csv": (
        "clip_id",
        "source_id",
        "audio_relpath",
        "transcript",
        "duration_s",
        "sample_rate",
        "channels",
        "peak_dbfs",
        "noise_floor_dbfs",
        "snr_db",
        "silence_ratio",
        "clipping_ratio",
        "voiced_ratio",
        "f0_min_hz",
        "f0_median_hz",
        "f0_max_hz",
        "audio_sha256",
        "review_status",
        "reviewer",
        "review_notes",
    ),
    "evaluation_cases.csv": (
        "case_id",
        "range",
        "source_audio_relpath",
        "lyrics",
        "start_ms",
        "end_ms",
        "audio_sha256",
        "notes",
    ),
    "versions.csv": (
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
    "ab_reviews.csv": (
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
    "production_jobs.csv": (
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
}
SPLIT_COLUMNS = ("clip_id", "source_id", "split", "audio_sha256", "dataset_revision")
REVIEW_STATUSES = frozenset({"pending", "accepted", "rejected"})
EVALUATION_RANGES = frozenset({"low", "mid", "high"})


@dataclass(frozen=True, slots=True)
class SplitSummary:
    dataset_revision: str
    train_sources: int
    validation_sources: int
    train_clips: int
    validation_clips: int


@dataclass(frozen=True, slots=True)
class TrainingStep:
    name: str
    command: tuple[str, ...]
    cwd: str
    success_exit_codes: tuple[int, ...] = (0,)
    required_outputs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": list(self.command),
            "cwd": self.cwd,
            "success_exit_codes": list(self.success_exit_codes),
            "required_outputs": list(self.required_outputs),
        }


def load_project(root: Path) -> dict[str, Any]:
    config_path = root / "project.toml"
    try:
        with config_path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"无法读取项目配置：{config_path}") from error
    if not isinstance(loaded, dict):
        raise ValueError("project.toml 根节点必须是表")
    return loaded


def validate_workspace(root: Path, *, stage: str = "scaffold") -> list[str]:
    """返回工作区问题；scaffold 阶段允许清单只有表头。"""
    if stage not in {"scaffold", "dataset", "evaluation"}:
        raise ValueError(f"未知校验阶段：{stage}")
    errors: list[str] = []
    try:
        project = load_project(root)
    except ValueError as error:
        return [str(error)]
    errors.extend(_validate_project_config(project))
    rows_by_manifest: dict[str, list[dict[str, str]]] = {}
    for filename, required in MANIFEST_COLUMNS.items():
        path = root / "manifests" / filename
        header, rows, read_error = _read_manifest(path)
        if read_error:
            errors.append(read_error)
            continue
        missing = [column for column in required if column not in header]
        if missing:
            errors.append(f"{filename} 缺少列：{', '.join(missing)}")
        rows_by_manifest[filename] = rows

    errors.extend(_validate_sources(rows_by_manifest.get("sources.csv", [])))
    errors.extend(_validate_clips(rows_by_manifest.get("clips.csv", [])))
    if stage in {"dataset", "evaluation"}:
        errors.extend(_validate_frozen_dataset(root, rows_by_manifest.get("clips.csv", [])))
    if stage == "evaluation":
        evaluation_rows = rows_by_manifest.get("evaluation_cases.csv", [])
        errors.extend(_validate_evaluation_cases(evaluation_rows))
        errors.extend(_validate_evaluation_lock(root, evaluation_rows))
    return errors


def freeze_split(root: Path, *, force: bool = False) -> SplitSummary:
    """按 source_id 冻结训练/验证划分，杜绝同源增强片段泄漏。"""
    errors = validate_workspace(root, stage="scaffold")
    if errors:
        raise ValueError("工作区校验失败：" + "; ".join(errors))
    output_path = root / "manifests" / "split.csv"
    if output_path.exists() and not force:
        raise FileExistsError(f"固定划分 already exists：{output_path}")

    project = load_project(root)
    data = _table(project, "data")
    ratio = float(data["validation_ratio"])
    seed = str(data["split_seed"])
    _, clips, read_error = _read_manifest(root / "manifests" / "clips.csv")
    if read_error:
        raise ValueError(read_error)
    accepted = [row for row in clips if row.get("review_status", "").strip() == "accepted"]
    sources = sorted({row.get("source_id", "").strip() for row in accepted} - {""})
    if len(sources) < 2:
        raise ValueError("冻结划分至少需要两个通过人工复核的 source_id")

    ranked_sources = sorted(
        sources,
        key=lambda source_id: hashlib.sha256(f"{seed}\0{source_id}".encode()).hexdigest(),
    )
    validation_count = max(1, min(len(sources) - 1, round(len(sources) * ratio)))
    validation_sources = frozenset(ranked_sources[:validation_count])
    revision = _dataset_revision(accepted, seed=seed, ratio=ratio)
    split_rows = [
        {
            "clip_id": row["clip_id"].strip(),
            "source_id": row["source_id"].strip(),
            "split": "validation" if row["source_id"].strip() in validation_sources else "train",
            "audio_sha256": row["audio_sha256"].strip().lower(),
            "dataset_revision": revision,
        }
        for row in sorted(accepted, key=lambda item: item["clip_id"])
    ]
    _write_manifest(output_path, SPLIT_COLUMNS, split_rows)
    train_clips = sum(row["split"] == "train" for row in split_rows)
    validation_clips = len(split_rows) - train_clips
    return SplitSummary(
        dataset_revision=revision,
        train_sources=len(sources) - validation_count,
        validation_sources=validation_count,
        train_clips=train_clips,
        validation_clips=validation_clips,
    )


def build_rvc_plan(root: Path, *, run_id: str) -> list[TrainingStep]:
    """构造可审计的 RVC v2 + RMVPE 命令，不执行也不自动发布。"""
    if not run_id.strip():
        raise ValueError("run_id 不能为空")
    project = load_project(root)
    baseline = _table(project, "baseline")
    runtime = _table(project, "runtime")
    data = _table(project, "data")
    if baseline.get("engine") != "rvc" or baseline.get("version") != "v2":
        raise ValueError("Baseline 必须是 RVC v2")
    if baseline.get("f0_method") != "rmvpe":
        raise ValueError("Baseline 必须使用 RMVPE")

    rvc_root = Path(str(runtime["rvc_root"]))
    python = str(runtime["rvc_python"])
    gpu = str(runtime["gpu"])
    sample_rate = str(data["sample_rate"])
    sample_rate_tag = {32000: "32k", 40000: "40k", 48000: "48k"}.get(int(data["sample_rate"]))
    if sample_rate_tag is None:
        raise ValueError("RVC 只支持 32000、40000 或 48000 Hz")
    version = str(baseline["version"])
    experiment = run_id.strip()
    log_dir = str(rvc_root / "logs" / experiment)
    dataset_dir = str((root / "audio" / "dataset" / "train").resolve())
    workers = str(int(baseline.get("workers", 4)))
    cwd = str(rvc_root)
    pretrained_g = str(rvc_root / "assets" / "pretrained_v2" / f"f0G{sample_rate_tag}.pth")
    pretrained_d = str(rvc_root / "assets" / "pretrained_v2" / f"f0D{sample_rate_tag}.pth")
    repository_root = Path(__file__).resolve().parents[2]
    experiment_script = str(repository_root / "scripts" / "train" / "prepare_rvc_experiment.py")
    index_script = str(repository_root / "scripts" / "train" / "build_index.py")
    steps = [
        TrainingStep(
            "preprocess",
            (
                python,
                "infer/modules/train/preprocess.py",
                dataset_dir,
                sample_rate,
                workers,
                log_dir,
                "False",
                "3.7",
            ),
            cwd,
        ),
    ]
    steps.extend(
        TrainingStep(
            f"extract-rmvpe-{part}",
            (
                python,
                "infer/modules/train/extract/extract_f0_rmvpe.py",
                workers,
                str(part),
                gpu,
                log_dir,
                "False",
            ),
            cwd,
        )
        for part in range(int(workers))
    )
    steps.extend(
        TrainingStep(
            f"extract-features-{part}",
            (
                python,
                "infer/modules/train/extract_feature_print.py",
                "cuda",
                workers,
                str(part),
                gpu,
                log_dir,
                version,
                "False",
            ),
            cwd,
        )
        for part in range(int(workers))
    )
    steps.extend(
        [
            TrainingStep(
                "prepare-experiment",
                (
                    python,
                    experiment_script,
                    "--rvc-root",
                    str(rvc_root),
                    "--experiment",
                    experiment,
                    "--sample-rate",
                    sample_rate_tag,
                    "--version",
                    version,
                ),
                cwd,
                required_outputs=(
                    str(Path(log_dir) / "config.json"),
                    str(Path(log_dir) / "filelist.txt"),
                ),
            ),
            TrainingStep(
                "train",
                (
                    python,
                    "infer/modules/train/train.py",
                    "-e",
                    experiment,
                    "-sr",
                    sample_rate_tag,
                    "-f0",
                    "1",
                    "-bs",
                    str(baseline["batch_size"]),
                    "-g",
                    gpu,
                    "-te",
                    str(baseline["epochs"]),
                    "-se",
                    str(baseline["save_every_epochs"]),
                    "-l",
                    "1",
                    "-c",
                    "0",
                    "-sw",
                    "1",
                    "-v",
                    version,
                    "-pg",
                    pretrained_g,
                    "-pd",
                    pretrained_d,
                ),
                cwd,
                success_exit_codes=(0, 2333333),
                required_outputs=(str(rvc_root / "assets" / "weights" / f"{experiment}.pth"),),
            ),
            TrainingStep(
                "build-index",
                (
                    python,
                    index_script,
                    "--rvc-root",
                    str(rvc_root),
                    "--experiment",
                    experiment,
                    "--version",
                    version,
                ),
                cwd,
                required_outputs=(str(Path(log_dir) / "index.receipt.json"),),
            ),
        ]
    )
    return steps


def freeze_evaluation(root: Path, *, force: bool = False) -> str:
    """冻结固定测试片段的身份，不复制或修改测试音频。"""
    path = root / "manifests" / "evaluation.lock.json"
    if path.exists() and not force:
        raise FileExistsError(f"固定评测 already exists：{path}")
    header, rows, read_error = _read_manifest(root / "manifests" / "evaluation_cases.csv")
    if read_error:
        raise ValueError(read_error)
    missing = [
        column for column in MANIFEST_COLUMNS["evaluation_cases.csv"] if column not in header
    ]
    if missing:
        raise ValueError(f"evaluation_cases.csv 缺少列：{', '.join(missing)}")
    errors = _validate_evaluation_cases(rows)
    if errors:
        raise ValueError("固定评测校验失败：" + "; ".join(errors))
    revision = _evaluation_revision(rows)
    payload = {
        "schema_version": 1,
        "evaluation_revision": revision,
        "case_count": len(rows),
        "ranges": sorted({row["range"].strip() for row in rows}),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return revision


def _validate_project_config(project: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if project.get("schema_version") != 1:
        errors.append("project.toml schema_version 必须为 1")
    for field in ("project_id", "display_name"):
        if not isinstance(project.get(field), str) or not str(project[field]).strip():
            errors.append(f"project.toml {field} 必须为非空字符串")
    try:
        data = _table(project, "data")
        baseline = _table(project, "baseline")
        runtime = _table(project, "runtime")
        inference = _table(project, "inference")
    except ValueError as error:
        return [str(error)]
    if data.get("sample_rate") != 48000 or data.get("channels") != 1:
        errors.append("数据格式必须是 48000 Hz 单声道")
    ratio = data.get("validation_ratio")
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0 < ratio < 1:
        errors.append("validation_ratio 必须在 0 与 1 之间")
    if not str(data.get("split_seed", "")).strip():
        errors.append("split_seed 不能为空")
    if (baseline.get("engine"), baseline.get("version"), baseline.get("f0_method")) != (
        "rvc",
        "v2",
        "rmvpe",
    ):
        errors.append("Baseline 必须固定为 RVC v2 + RMVPE")
    for field in ("epochs", "save_every_epochs", "batch_size"):
        value = baseline.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"baseline.{field} 必须为正整数")
    for field in ("rvc_root", "rvc_python", "gpu"):
        if not str(runtime.get(field, "")).strip():
            errors.append(f"runtime.{field} 不能为空")
    for field in ("index_rate", "rms_mix_rate", "protect"):
        value = inference.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
            errors.append(f"inference.{field} 必须在 0 与 1 之间")
    return errors


def _validate_sources(rows: Sequence[Mapping[str, str]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        source_id = row.get("source_id", "").strip()
        if not source_id:
            errors.append(f"sources.csv:{line} source_id 不能为空")
        elif source_id in seen:
            errors.append(f"sources.csv:{line} source_id 重复：{source_id}")
        seen.add(source_id)
        for field in ("audio_relpath", "transcript", "source_reference", "usage_rights"):
            if not row.get(field, "").strip():
                errors.append(f"sources.csv:{line} {field} 不能为空")
    return errors


def _validate_clips(rows: Sequence[Mapping[str, str]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        clip_id = row.get("clip_id", "").strip()
        if not clip_id:
            errors.append(f"clips.csv:{line} clip_id 不能为空")
        elif clip_id in seen:
            errors.append(f"clips.csv:{line} clip_id 重复：{clip_id}")
        seen.add(clip_id)
        status = row.get("review_status", "").strip()
        if status not in REVIEW_STATUSES:
            errors.append(f"clips.csv:{line} review_status 必须是 pending/accepted/rejected")
        if status == "accepted":
            for field in (
                "source_id",
                "audio_relpath",
                "transcript",
                "audio_sha256",
                "reviewer",
            ):
                if not row.get(field, "").strip():
                    errors.append(f"clips.csv:{line} 已接受片段的 {field} 不能为空")
            digest = row.get("audio_sha256", "").strip()
            if digest and (
                len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest)
            ):
                errors.append(f"clips.csv:{line} audio_sha256 必须是 64 位十六进制")
    return errors


def _validate_frozen_dataset(root: Path, clips: Sequence[Mapping[str, str]]) -> list[str]:
    path = root / "manifests" / "split.csv"
    header, rows, read_error = _read_manifest(path)
    if read_error:
        return ["数据集阶段必须先运行 freeze-split：" + read_error]
    missing = [column for column in SPLIT_COLUMNS if column not in header]
    if missing:
        return [f"split.csv 缺少列：{', '.join(missing)}"]
    accepted_ids = {
        row.get("clip_id", "").strip()
        for row in clips
        if row.get("review_status", "").strip() == "accepted"
    }
    split_ids = {row.get("clip_id", "").strip() for row in rows}
    errors: list[str] = []
    if not accepted_ids or split_ids != accepted_ids:
        errors.append("split.csv 必须且只能覆盖全部 accepted 片段")
    source_splits: dict[str, set[str]] = {}
    revisions: set[str] = set()
    for row in rows:
        source_splits.setdefault(row.get("source_id", "").strip(), set()).add(
            row.get("split", "").strip()
        )
        revisions.add(row.get("dataset_revision", "").strip())
    if any(len(splits) != 1 for splits in source_splits.values()):
        errors.append("split.csv 存在同源片段跨 train/validation 泄漏")
    all_splits = {next(iter(splits), "") for splits in source_splits.values()}
    if all_splits != {"train", "validation"}:
        errors.append("split.csv 必须同时包含 train 和 validation")
    if len(revisions) != 1 or "" in revisions:
        errors.append("split.csv 必须固定为唯一非空 dataset_revision")
    return errors


def _validate_evaluation_cases(rows: Sequence[Mapping[str, str]]) -> list[str]:
    if not rows:
        return ["evaluation_cases.csv 至少需要低、中、高三个固定测试片段"]
    errors: list[str] = []
    ranges = {row.get("range", "").strip() for row in rows}
    if not EVALUATION_RANGES.issubset(ranges):
        missing = ", ".join(sorted(EVALUATION_RANGES - ranges))
        errors.append(f"evaluation_cases.csv 缺少音区：{missing}")
    for line, row in enumerate(rows, start=2):
        for field in (
            "case_id",
            "source_audio_relpath",
            "lyrics",
            "start_ms",
            "end_ms",
            "audio_sha256",
        ):
            if not row.get(field, "").strip():
                errors.append(f"evaluation_cases.csv:{line} {field} 不能为空")
    return errors


def _validate_evaluation_lock(root: Path, rows: Sequence[Mapping[str, str]]) -> list[str]:
    path = root / "manifests" / "evaluation.lock.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["评测阶段必须先运行 freeze-evaluation"]
    if payload.get("schema_version") != 1:
        return ["evaluation.lock.json schema_version 必须为 1"]
    if payload.get("evaluation_revision") != _evaluation_revision(rows):
        return ["evaluation_cases.csv 已偏离冻结的 evaluation revision"]
    return []


def _evaluation_revision(rows: Iterable[Mapping[str, str]]) -> str:
    stable = [
        {
            field: row.get(field, "").strip()
            for field in MANIFEST_COLUMNS["evaluation_cases.csv"]
            if field != "notes"
        }
        for row in rows
    ]
    encoded = json.dumps(
        sorted(stable, key=lambda row: row["case_id"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _dataset_revision(rows: Iterable[Mapping[str, str]], *, seed: str, ratio: float) -> str:
    stable = [
        {
            "clip_id": row.get("clip_id", "").strip(),
            "source_id": row.get("source_id", "").strip(),
            "audio_sha256": row.get("audio_sha256", "").strip().lower(),
        }
        for row in rows
    ]
    payload = {
        "seed": seed,
        "validation_ratio": ratio,
        "clips": sorted(stable, key=lambda row: row["clip_id"]),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _table(values: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = values.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"project.toml 缺少 [{field}] 表")
    return value


def _read_manifest(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return [], [], f"清单缺少表头：{path}"
            return list(reader.fieldnames), list(reader), ""
    except OSError:
        return [], [], f"无法读取清单：{path}"


def _write_manifest(
    path: Path,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Animetta 角色翻唱工作区")
    parser.add_argument("--project", type=Path, default=Path("songs"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="校验配置和清单")
    check.add_argument("--stage", choices=("scaffold", "dataset", "evaluation"), default="scaffold")
    split = subparsers.add_parser("freeze-split", help="按 source_id 冻结数据集划分")
    split.add_argument("--force", action="store_true")
    evaluation = subparsers.add_parser("freeze-evaluation", help="冻结固定评测集身份")
    evaluation.add_argument("--force", action="store_true")
    plan = subparsers.add_parser("plan", help="输出不执行的 RVC 命令计划")
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.project.resolve()
    try:
        if args.command == "check":
            errors = validate_workspace(root, stage=args.stage)
            if errors:
                for error in errors:
                    print(f"[ERROR] {error}", file=sys.stderr)
                return 1
            print(f"工作区校验通过：{root} ({args.stage})")
            return 0
        if args.command == "freeze-split":
            summary = freeze_split(root, force=args.force)
            print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
            return 0
        if args.command == "freeze-evaluation":
            revision = freeze_evaluation(root, force=args.force)
            print(json.dumps({"evaluation_revision": revision}, ensure_ascii=False, indent=2))
            return 0
        plan = [step.as_dict() for step in build_rvc_plan(root, run_id=args.run_id)]
        payload = json.dumps({"schema_version": 1, "steps": plan}, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload + "\n", encoding="utf-8")
            print(f"训练计划已写入：{args.output}")
        else:
            print(payload)
        return 0
    except (FileExistsError, KeyError, OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
