from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from evaluations.livestream import pipeline as pipeline_module
from evaluations.livestream.cleaning import SemanticDecision, SemanticRequest
from evaluations.livestream.dataset import DatasetValidator, DatasetWriter, HeatTier
from evaluations.livestream.pipeline import CleanOptions, publish_clean_datasets


class TranslatingProcessor:
    def __init__(self, *, invalid_output: bool = False) -> None:
        self.invalid_output = invalid_output

    async def process_batch(
        self,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]:
        return [
            SemanticDecision(
                sequence=request.sequence,
                keep=True,
                intent="question",
                text_zh="this remains an English sentence"
                if self.invalid_output
                else f"第{request.sequence}条翻译后的中文问题是什么？",
                reason="",
            )
            for request in requests
        ]


class AlternatingProcessor:
    async def process_batch(
        self,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]:
        return [
            SemanticDecision(
                sequence=request.sequence,
                keep=request.sequence % 2 == 0,
                intent="question" if request.sequence % 2 == 0 else "",
                text_zh=f"第{request.sequence}条中文问题是什么？"
                if request.sequence % 2 == 0
                else "",
                reason="noise" if request.sequence % 2 else "",
            )
            for request in requests
        ]


def _source(path: Path) -> dict[str, object]:
    writer = DatasetWriter(path, dataset_id="source-low", heat_tier=HeatTier.LOW)
    sequence = 0
    for minute in range(2):
        for index in range(6):
            writer.write(
                LivestreamEvent(
                    sequence=sequence,
                    offset_ms=minute * 60_000 + index * 10_000,
                    event_type=LivestreamEventType.DANMAKU,
                    actor_id=f"raw-user-{index}",
                    text=f"what should we do next {sequence}?",
                    payload={"user_id": index + 1},
                ),
            )
            sequence += 1
    return writer.finalize(duration_ms=120_000)


def _high_source(path: Path) -> dict[str, object]:
    writer = DatasetWriter(path, dataset_id="source-high", heat_tier=HeatTier.HIGH)
    sequence = 0
    for minute in range(4):
        for index in range(80):
            writer.write(
                LivestreamEvent(
                    sequence=sequence,
                    offset_ms=minute * 60_000 + index * 750,
                    event_type=LivestreamEventType.DANMAKU,
                    actor_id=f"raw-user-{index % 20}",
                    text=f"foreign chat message {sequence}?",
                    payload={"user_id": index + 1},
                ),
            )
            sequence += 1
    return writer.finalize(duration_ms=240_000)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_pipeline_publishes_valid_real_and_enriched_pairs_atomically(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-low"
    source_manifest = _source(source)
    source_hashes = {name: _sha256(source / name) for name in ("manifest.json", "events.jsonl")}
    output_root = tmp_path / "outputs"

    published = await publish_clean_datasets(
        source,
        output_root,
        processor=TranslatingProcessor(),
        options=CleanOptions(seed=20260717, synthetic_ratio=0.10),
    )

    assert [path.name for path in published] == [
        "source-low-clean-real-v2",
        "source-low-clean-enriched-v2",
    ]
    real_result = DatasetValidator().validate(published[0], parent_dir=source)
    enriched_result = DatasetValidator().validate(published[1], parent_dir=published[0])
    assert real_result.valid is True
    assert enriched_result.valid is True
    assert (
        real_result.manifest["parent_dataset"]["events_sha256"] == source_manifest["events_sha256"]
    )
    assert enriched_result.manifest["parent_dataset"]["dataset_id"] == published[0].name
    assert real_result.manifest["cleaning_counts"]["translated"] == 12
    assert enriched_result.manifest["cleaning_counts"]["synthetic"] == 2
    assert real_result.manifest["processing"]["prompt_version"] == "zh-clean-v2"
    assert source_hashes == {
        name: _sha256(source / name) for name in ("manifest.json", "events.jsonl")
    }
    assert not any(path.name.startswith(".clean-staging-") for path in output_root.iterdir())


async def test_pipeline_records_minimum_high_timeline_compression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source-high"
    _high_source(source)
    output_root = tmp_path / "outputs"
    monkeypatch.setattr(pipeline_module, "_MIN_HIGH_DURATION_MS", 120_000)

    published = await publish_clean_datasets(
        source,
        output_root,
        processor=AlternatingProcessor(),
        options=CleanOptions(),
    )

    real = DatasetValidator().validate(published[0], parent_dir=source)
    enriched = DatasetValidator().validate(published[1], parent_dir=published[0])
    assert real.valid is True
    assert enriched.valid is True
    assert real.manifest["duration_ms"] >= 120_000
    assert real.manifest["derivation"] == {
        "kind": "high_time_compression",
        "compression_factor": 1.55,
        "original_duration_ms": 240_000,
    }


def test_pipeline_reserves_ninety_minutes_for_the_complete_high_burst_profile() -> None:
    assert pipeline_module._MIN_HIGH_DURATION_MS == 90 * 60 * 1000


async def test_published_pair_reopens_when_parent_directory_is_an_alias(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "datasets"
    source = dataset_root / "_source-capture"
    _source(source)

    published = await publish_clean_datasets(
        source,
        dataset_root,
        processor=TranslatingProcessor(),
        options=CleanOptions(),
    )

    assert DatasetValidator().validate(published[0]).valid is True
    assert DatasetValidator().validate(published[1]).valid is True


async def test_pipeline_removes_staging_and_publishes_nothing_on_validation_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-low"
    _source(source)
    output_root = tmp_path / "outputs"

    with pytest.raises(ValueError, match="validation") as exc_info:
        await publish_clean_datasets(
            source,
            output_root,
            processor=TranslatingProcessor(invalid_output=True),
            options=CleanOptions(),
        )

    assert "source-low-clean-real-v2:non_chinese_text" in str(exc_info.value)
    assert list(output_root.iterdir()) == []


async def test_pipeline_refuses_to_overwrite_either_output(tmp_path: Path) -> None:
    source = tmp_path / "source-low"
    _source(source)
    output_root = tmp_path / "outputs"
    existing = output_root / "source-low-clean-enriched-v2"
    existing.mkdir(parents=True)

    with pytest.raises(FileExistsError, match="already exists"):
        await publish_clean_datasets(
            source,
            output_root,
            processor=TranslatingProcessor(),
            options=CleanOptions(),
        )

    assert not (output_root / "source-low-clean-real-v2").exists()
    assert existing.is_dir()


def test_clean_options_reject_unsupported_contract_values() -> None:
    with pytest.raises(ValueError, match="balanced"):
        CleanOptions(profile="aggressive")
    with pytest.raises(ValueError, match="zh-CN"):
        CleanOptions(target_language="en-US")
    with pytest.raises(ValueError, match="0.10"):
        CleanOptions(synthetic_ratio=0.20)
