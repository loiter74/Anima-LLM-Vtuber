"""统一角色语音格式并生成待人工复核的音频质检清单。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import re
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf

from scripts.train.workspace import MANIFEST_COLUMNS, load_project, validate_workspace

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _resolve_inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"路径越出工作区：{relative}") from error
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dbfs(amplitude: float) -> float:
    return 20.0 * math.log10(max(amplitude, 1e-12))


def _format(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def analyze_audio(
    audio: np.ndarray,
    sample_rate: int,
    *,
    source_clipping_ratio: float,
    qc: Mapping[str, Any],
) -> tuple[dict[str, str], list[str]]:
    """计算供筛选使用的确定性代理指标；最终判断仍由人工听审。"""
    duration = len(audio) / sample_rate
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    frame_length = min(2048, max(256, 2 ** int(math.log2(max(len(audio), 256)))))
    hop_length = max(64, frame_length // 4)
    rms = librosa.feature.rms(
        y=audio,
        frame_length=frame_length,
        hop_length=hop_length,
        center=True,
    )[0]
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-12))
    silence_threshold = float(qc["silence_threshold_dbfs"])
    silence_ratio = float(np.mean(rms_db < silence_threshold))
    noise_floor = float(np.percentile(rms_db, 10))
    signal_level = float(np.percentile(rms_db, 90))
    snr = signal_level - noise_floor

    f0_values = np.array([], dtype=np.float64)
    voiced_ratio = 0.0
    if len(audio) >= frame_length:
        try:
            f0, voiced, _ = librosa.pyin(
                audio,
                fmin=float(qc["f0_min_hz"]),
                fmax=float(qc["f0_max_hz"]),
                sr=sample_rate,
                frame_length=frame_length,
                hop_length=hop_length,
            )
            valid = voiced & np.isfinite(f0)
            f0_values = f0[valid]
            voiced_ratio = float(np.mean(valid))
        except (librosa.util.exceptions.ParameterError, ValueError):
            pass

    metrics = {
        "duration_s": _format(duration),
        "sample_rate": str(sample_rate),
        "channels": "1",
        "peak_dbfs": _format(_dbfs(peak)),
        "noise_floor_dbfs": _format(noise_floor),
        "snr_db": _format(snr),
        "silence_ratio": _format(silence_ratio),
        "clipping_ratio": _format(source_clipping_ratio),
        "voiced_ratio": _format(voiced_ratio),
        "f0_min_hz": _format(float(np.min(f0_values))) if f0_values.size else "",
        "f0_median_hz": _format(float(np.median(f0_values))) if f0_values.size else "",
        "f0_max_hz": _format(float(np.max(f0_values))) if f0_values.size else "",
    }
    flags: list[str] = []
    if duration < float(qc["min_duration_s"]):
        flags.append("too_short")
    if duration > float(qc["max_duration_s"]):
        flags.append("too_long")
    if silence_ratio > float(qc["max_silence_ratio"]):
        flags.append("excess_silence")
    if source_clipping_ratio > float(qc["max_clipping_ratio"]):
        flags.append("clipping")
    if snr < float(qc["min_snr_db"]):
        flags.append("low_snr_proxy")
    if not f0_values.size:
        flags.append("pitch_unresolved")
    return metrics, flags


def _process_source(
    root: Path,
    row: Mapping[str, str],
    *,
    project: Mapping[str, Any],
    existing: Mapping[str, str] | None,
) -> dict[str, str]:
    source_id = row["source_id"].strip()
    if not SAFE_ID.fullmatch(source_id):
        raise ValueError(f"source_id 只能包含字母、数字、点、下划线和连字符：{source_id}")
    source_path = _resolve_inside(root, row["audio_relpath"].strip())
    if not source_path.is_file():
        raise FileNotFoundError(f"原始音频不存在：{source_path}")
    samples, source_rate = sf.read(source_path, dtype="float32", always_2d=True)
    source_clipping_ratio = float(np.mean(np.abs(samples) >= 0.999))
    mono = np.asarray(np.mean(samples, axis=1, dtype=np.float32), dtype=np.float32)
    target_rate = int(project["data"]["sample_rate"])
    if source_rate != target_rate:
        mono = librosa.resample(mono, orig_sr=source_rate, target_sr=target_rate)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    peak_cap = 10 ** (-1.0 / 20.0)
    if peak > peak_cap:
        mono = mono * (peak_cap / peak)

    output = root / "audio" / "processed" / f"{source_id}.wav"
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, mono, target_rate, subtype="PCM_16")
    normalized, _ = sf.read(output, dtype="float32", always_2d=False)
    metrics, flags = analyze_audio(
        np.asarray(normalized, dtype=np.float32),
        target_rate,
        source_clipping_ratio=source_clipping_ratio,
        qc={
            **project["qc"],
            "min_duration_s": project["data"]["min_duration_s"],
            "max_duration_s": project["data"]["max_duration_s"],
        },
    )
    digest = _sha256(output)
    preserve_review = existing is not None and existing.get("audio_sha256", "") == digest
    review_status = existing.get("review_status", "pending") if preserve_review else "pending"
    reviewer = existing.get("reviewer", "") if preserve_review else ""
    previous_notes = existing.get("review_notes", "") if preserve_review else ""
    automatic_notes = "auto_flags=" + ("|".join(flags) if flags else "none")
    review_notes = previous_notes or automatic_notes
    result = dict.fromkeys(MANIFEST_COLUMNS["clips.csv"], "")
    result.update(
        {
            "clip_id": source_id,
            "source_id": source_id,
            "audio_relpath": output.relative_to(root).as_posix(),
            "transcript": row["transcript"].strip(),
            **metrics,
            "audio_sha256": digest,
            "review_status": review_status,
            "reviewer": reviewer,
            "review_notes": review_notes,
        }
    )
    return result


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _process_source_task(
    task: tuple[Path, Mapping[str, str], Mapping[str, Any], Mapping[str, str] | None],
) -> tuple[dict[str, str] | None, str | None]:
    root, row, project, existing = task
    try:
        return _process_source(root, row, project=project, existing=existing), None
    except (OSError, RuntimeError, ValueError) as error:
        source_id = row.get("source_id", "<missing>")
        return None, f"{source_id}: {error}"


def _process_sources(
    root: Path,
    sources: Sequence[Mapping[str, str]],
    *,
    project: Mapping[str, Any],
    existing: Mapping[str, Mapping[str, str]],
    workers: int,
) -> tuple[list[dict[str, str]], list[str]]:
    if workers < 1:
        raise ValueError("workers 必须大于等于 1")

    tasks = [(root, row, project, existing.get(row["source_id"])) for row in sources]
    if workers == 1:
        results = list(map(_process_source_task, tasks))
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(_process_source_task, tasks))
    processed = [result for result, _failure in results if result is not None]
    failures = [failure for _result, failure in results if failure is not None]
    return processed, failures


def prepare_workspace(root: Path, *, workers: int = 1) -> int:
    errors = validate_workspace(root, stage="scaffold")
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    project = load_project(root)
    sources = _read_rows(root / "manifests" / "sources.csv")
    if not sources:
        print("[ERROR] sources.csv 还没有数据", file=sys.stderr)
        return 1
    existing = {
        row["clip_id"].strip(): row
        for row in _read_rows(root / "manifests" / "clips.csv")
        if row.get("clip_id", "").strip()
    }
    processed, failures = _process_sources(
        root,
        sources,
        project=project,
        existing=existing,
        workers=workers,
    )
    if failures:
        for failure in failures:
            print(f"[ERROR] {failure}", file=sys.stderr)
        print("clips.csv 未更新；修复全部来源后重试。", file=sys.stderr)
        return 1

    destination = root / "manifests" / "clips.csv"
    temporary = destination.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=MANIFEST_COLUMNS["clips.csv"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(sorted(processed, key=lambda row: row["clip_id"]))
    temporary.replace(destination)
    flagged = sum("auto_flags=none" not in row["review_notes"] for row in processed)
    print(f"已处理 {len(processed)} 条语音，其中 {flagged} 条需优先人工复核。")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一角色语音格式并生成 QC 清单")
    parser.add_argument("--project", type=Path, default=Path("songs"))
    parser.add_argument("--workers", type=int, default=1, help="并行处理进程数，默认 1")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return prepare_workspace(args.project.resolve(), workers=args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
