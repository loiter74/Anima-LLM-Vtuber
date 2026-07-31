from __future__ import annotations

import csv
import json
from pathlib import Path

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from evaluations.livestream.cleaning import CleaningResult, DropRecord
from evaluations.livestream.cleaning_evidence import write_cleaning_evidence
from evaluations.livestream.dataset import DatasetValidationResult


def _real(sequence: int) -> LivestreamEvent:
    return LivestreamEvent(
        sequence=sequence,
        offset_ms=sequence * 1_000,
        event_type=LivestreamEventType.DANMAKU,
        actor_id=f"viewer_{sequence + 1:04d}",
        text=f"第{sequence}条清洗后的中文问题？",
        payload={"origin": "real", "source_sequence": sequence + 20, "intent": "question"},
    )


def _synthetic(sequence: int) -> LivestreamEvent:
    return LivestreamEvent(
        sequence=sequence,
        offset_ms=sequence * 1_000 + 1,
        event_type=LivestreamEventType.DANMAKU,
        actor_id=f"synthetic_{sequence + 1:04d}",
        text="[合成补充]你觉得刚才的选择合理吗？",
        payload={
            "origin": "synthetic",
            "intent": "question",
            "scenario": "direct_question",
            "parent_sequence": sequence,
        },
    )


def _datasets() -> dict[str, DatasetValidationResult]:
    real = [_real(index) for index in range(5)]
    synthetic = [_synthetic(5)]
    workload = {"rate_p50": 5.0, "qualification_ratio": 1.0}
    return {
        "sample-clean-real-v2": DatasetValidationResult(
            valid=True,
            manifest={
                "dataset_id": "sample-clean-real-v2",
                "variant": "clean-real",
                "synthetic_ratio": 0.0,
                "workload": workload,
                "effective_workload": workload,
            },
            events=real,
        ),
        "sample-clean-enriched-v2": DatasetValidationResult(
            valid=True,
            manifest={
                "dataset_id": "sample-clean-enriched-v2",
                "variant": "clean-enriched",
                "synthetic_ratio": 0.1,
                "workload": workload,
                "effective_workload": {"rate_p50": 6.0, "qualification_ratio": 1.0},
            },
            events=[*real, *synthetic],
        ),
    }


def test_cleaning_evidence_writes_summary_markdown_and_privacy_safe_review_csv(
    tmp_path: Path,
) -> None:
    result = CleaningResult(
        events=[_real(index) for index in range(5)],
        drops=[
            DropRecord(source_sequence=91, text_hash="a" * 64, reason="emote_only"),
            DropRecord(source_sequence=92, text_hash="b" * 64, reason="symbol_only"),
        ],
        translated_count=3,
        intent_counts={"question": 5},
    )

    paths = write_cleaning_evidence(
        tmp_path,
        source_replyable_count=7,
        cleaning_result=result,
        datasets=_datasets(),
        seed=20260717,
    )

    assert set(paths) == {"json", "markdown", "review_csv"}
    summary = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert summary["retained_count"] == 5
    assert summary["dropped_count"] == 2
    assert summary["retention_rate"] == 5 / 7
    assert summary["translated_count"] == 3
    assert summary["drop_reasons"] == {"emote_only": 1, "symbol_only": 1}
    assert summary["datasets"]["sample-clean-enriched-v2"]["synthetic_count"] == 1
    assert "真实负载" in paths["markdown"].read_text(encoding="utf-8")

    with paths["review_csv"].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["category"] for row in rows} == {"retained", "dropped", "synthetic"}
    assert all(row["text_zh"] == "" for row in rows if row["category"] == "dropped")
    assert all(len(row["text_hash"]) == 64 for row in rows)

    serialized = "\n".join(path.read_text(encoding="utf-8-sig") for path in paths.values())
    assert "raw English source sentence" not in serialized
    assert "api_key" not in serialized


def test_cleaning_review_sampling_is_fixed_seed_deterministic(tmp_path: Path) -> None:
    result = CleaningResult(
        events=[_real(index) for index in range(50)],
        drops=[
            DropRecord(source_sequence=index, text_hash=f"{index:064x}", reason="noise")
            for index in range(50)
        ],
        translated_count=10,
        intent_counts={"question": 50},
    )

    first = write_cleaning_evidence(
        tmp_path / "first",
        source_replyable_count=100,
        cleaning_result=result,
        datasets=_datasets(),
        seed=7,
    )["review_csv"].read_bytes()
    second = write_cleaning_evidence(
        tmp_path / "second",
        source_replyable_count=100,
        cleaning_result=result,
        datasets=_datasets(),
        seed=7,
    )["review_csv"].read_bytes()

    assert first == second
