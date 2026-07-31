"""Privacy-safe summaries and deterministic review samples for cleaning runs."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from .cleaning import CleaningResult
from .dataset import DatasetValidationResult


def write_cleaning_evidence(
    output_dir: Path,
    *,
    source_replyable_count: int,
    cleaning_result: CleaningResult,
    datasets: dict[str, DatasetValidationResult],
    seed: int,
) -> dict[str, Path]:
    """Write aggregate-only reports and Chinese/hash-only review rows."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary(
        source_replyable_count=source_replyable_count,
        cleaning_result=cleaning_result,
        datasets=datasets,
        seed=seed,
    )
    json_path = output_dir / "cleaning-report.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown_path = output_dir / "cleaning-report.md"
    markdown_path.write_text(
        _markdown(summary),
        encoding="utf-8",
        newline="\n",
    )
    review_path = output_dir / "manual-review.csv"
    _write_review(review_path, cleaning_result=cleaning_result, datasets=datasets, seed=seed)
    return {"json": json_path, "markdown": markdown_path, "review_csv": review_path}


def _summary(
    *,
    source_replyable_count: int,
    cleaning_result: CleaningResult,
    datasets: dict[str, DatasetValidationResult],
    seed: int,
) -> dict[str, object]:
    retained_count = sum(
        event.payload.get("origin", "real") == "real"
        and event.to_danmaku_message(timestamp=0) is not None
        for event in cleaning_result.events
    )
    dataset_summaries: dict[str, object] = {}
    for dataset_id, result in sorted(datasets.items()):
        synthetic_count = sum(
            event.payload.get("origin") == "synthetic"
            for event in result.events
            if event.to_danmaku_message(timestamp=0) is not None
        )
        dataset_summaries[dataset_id] = {
            "variant": result.manifest.get("variant"),
            "synthetic_ratio": result.manifest.get("synthetic_ratio", 0.0),
            "synthetic_count": synthetic_count,
            "workload": result.manifest.get("workload", {}),
            "effective_workload": result.manifest.get("effective_workload", {}),
        }
    return {
        "seed": seed,
        "source_replyable_count": source_replyable_count,
        "retained_count": retained_count,
        "dropped_count": len(cleaning_result.drops),
        "retention_rate": retained_count / source_replyable_count
        if source_replyable_count
        else 0.0,
        "translated_count": cleaning_result.translated_count,
        "drop_reasons": dict(
            sorted(Counter(drop.reason for drop in cleaning_result.drops).items()),
        ),
        "intent_counts": dict(sorted(cleaning_result.intent_counts.items())),
        "datasets": dataset_summaries,
    }


def _markdown(summary: dict[str, object]) -> str:
    retention_rate = summary["retention_rate"]
    assert isinstance(retention_rate, (int, float))
    lines = [
        "# 直播弹幕清洗证据",
        "",
        f"- 来源可回复消息：{summary['source_replyable_count']}",
        f"- 保留消息：{summary['retained_count']}",
        f"- 删除消息：{summary['dropped_count']}",
        f"- 翻译消息：{summary['translated_count']}",
        f"- 保留率：{retention_rate:.2%}",
        "",
        "## 数据集负载",
        "",
        "| 数据集 | 版本 | 合成数 | 真实负载 P50 | 有效负载 P50 |",
        "|---|---|---:|---:|---:|",
    ]
    datasets = summary["datasets"]
    assert isinstance(datasets, dict)
    for dataset_id, raw in datasets.items():
        item = raw if isinstance(raw, dict) else {}
        workload = item.get("workload", {})
        effective = item.get("effective_workload", {})
        workload_p50 = workload.get("rate_p50", "") if isinstance(workload, dict) else ""
        effective_p50 = effective.get("rate_p50", "") if isinstance(effective, dict) else ""
        lines.append(
            f"| {dataset_id} | {item.get('variant', '')} | {item.get('synthetic_count', 0)} "
            f"| {workload_p50} | {effective_p50} |",
        )
    return "\n".join(lines) + "\n"


def _write_review(
    path: Path,
    *,
    cleaning_result: CleaningResult,
    datasets: dict[str, DatasetValidationResult],
    seed: int,
) -> None:
    retained = [
        {
            "category": "retained",
            "dataset_id": "",
            "sequence": event.payload.get("source_sequence", event.sequence),
            "text_hash": _text_hash(event.text),
            "text_zh": event.text,
            "reason": "",
            "intent": event.payload.get("intent", ""),
            "scenario": "",
        }
        for event in cleaning_result.events
        if event.to_danmaku_message(timestamp=0) is not None
    ]
    dropped = [
        {
            "category": "dropped",
            "dataset_id": "",
            "sequence": item.source_sequence,
            "text_hash": item.text_hash,
            "text_zh": "",
            "reason": item.reason,
            "intent": "",
            "scenario": "",
        }
        for item in cleaning_result.drops
    ]
    synthetic = [
        {
            "category": "synthetic",
            "dataset_id": dataset_id,
            "sequence": event.sequence,
            "text_hash": _text_hash(event.text),
            "text_zh": event.text,
            "reason": "",
            "intent": event.payload.get("intent", ""),
            "scenario": event.payload.get("scenario", ""),
        }
        for dataset_id, result in sorted(datasets.items())
        for event in result.events
        if event.payload.get("origin") == "synthetic"
    ]
    rows: list[dict[str, object]] = []
    for index, candidates in enumerate((retained, dropped, synthetic)):
        ordered = sorted(
            candidates,
            key=lambda row: (str(row["dataset_id"]), int(row["sequence"])),
        )
        random.Random(seed + index).shuffle(ordered)
        rows.extend(ordered[:20])
    fieldnames = [
        "category",
        "dataset_id",
        "sequence",
        "text_hash",
        "text_zh",
        "reason",
        "intent",
        "scenario",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
