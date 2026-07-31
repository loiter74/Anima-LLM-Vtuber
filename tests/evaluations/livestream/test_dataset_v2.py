from __future__ import annotations

import hashlib
import json
from pathlib import Path

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from evaluations.livestream.dataset import DatasetValidator, DatasetWriter, HeatTier


def _event(
    sequence: int,
    offset_ms: int,
    *,
    text: str = "这条弹幕有明确意图",
    actor_id: str = "viewer_0001",
    payload: dict[str, object] | None = None,
) -> LivestreamEvent:
    return LivestreamEvent(
        sequence=sequence,
        offset_ms=offset_ms,
        event_type=LivestreamEventType.DANMAKU,
        actor_id=actor_id,
        text=text,
        payload=payload
        or {
            "origin": "real",
            "source_sequence": sequence,
            "intent": "opinion",
        },
    )


def _write_source(path: Path) -> dict[str, object]:
    writer = DatasetWriter(path, dataset_id=path.name, heat_tier=HeatTier.LOW)
    writer.write(_event(0, 0, text="source one", actor_id="Alice", payload={"user_id": 1}))
    writer.write(_event(1, 60_000, text="source two", actor_id="Bob", payload={"user_id": 2}))
    return writer.finalize(duration_ms=120_000)


def _v2_writer(
    path: Path,
    parent: dict[str, object],
    *,
    variant: str = "clean-real",
    synthetic_ratio: float = 0.0,
) -> DatasetWriter:
    return DatasetWriter(
        path,
        dataset_id=path.name,
        heat_tier=HeatTier.LOW,
        schema_version=2,
        parent_dataset={
            "dataset_id": parent["dataset_id"],
            "events_sha256": parent["events_sha256"],
        },
        processing={
            "profile": "balanced",
            "target_language": "zh-CN",
            "cleaner_version": "1",
            "prompt_version": "1",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "seed": 20260717,
        },
        cleaning_counts={
            "retained": 2,
            "dropped": 0,
            "translated": 0,
            "synthetic": 0 if variant == "clean-real" else 1,
        },
        variant=variant,
        synthetic_ratio=synthetic_ratio,
    )


def _rewrite_events(output: Path, rows: list[dict[str, object]]) -> None:
    events_path = output / "events.jsonl"
    events_path.write_text(
        "".join(f"{json.dumps(row, ensure_ascii=False, separators=(',', ':'))}\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["events_sha256"] = hashlib.sha256(events_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_schema_v1_dataset_remains_readable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_source(source)

    result = DatasetValidator().validate(source)

    assert result.valid is True
    assert result.manifest["schema_version"] == 1
    assert "effective_workload" not in result.manifest


def test_schema_v2_manifest_records_parent_processing_and_effective_workload(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))

    manifest = writer.finalize(duration_ms=120_000)
    result = DatasetValidator().validate(output)

    assert result.valid is True
    assert manifest["schema_version"] == 2
    assert manifest["parent_dataset"] == {
        "dataset_id": "source",
        "events_sha256": parent["events_sha256"],
    }
    assert manifest["processing"]["target_language"] == "zh-CN"
    assert manifest["variant"] == "clean-real"
    assert manifest["cleaning_counts"] == {
        "retained": 2,
        "dropped": 0,
        "translated": 0,
        "synthetic": 0,
    }
    assert manifest["derivation"] is None
    assert manifest["synthetic_ratio"] == 0.0
    assert manifest["workload"] == manifest["effective_workload"]


def test_schema_v2_manifest_records_medium_derivation(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-medium-clean-real-v2"
    writer = DatasetWriter(
        output,
        dataset_id=output.name,
        heat_tier=HeatTier.LOW,
        schema_version=2,
        parent_dataset={
            "dataset_id": "source",
            "events_sha256": parent["events_sha256"],
        },
        processing={"profile": "balanced", "target_language": "zh-CN"},
        cleaning_counts={"retained": 2, "dropped": 0, "translated": 0, "synthetic": 0},
        derivation={"kind": "medium", "target_rate": 40, "seed": 20260717},
        variant="clean-real",
    )
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))

    manifest = writer.finalize(duration_ms=120_000)

    assert manifest["derivation"] == {
        "kind": "medium",
        "target_rate": 40,
        "seed": 20260717,
    }


def test_schema_v2_workload_uses_one_second_rolling_windows(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))

    manifest = writer.finalize(duration_ms=120_000)

    assert manifest["workload"]["window_seconds"] == 60
    assert manifest["workload"]["window_step_ms"] == 1_000
    assert manifest["workload"]["window_count"] == 61
    assert manifest["workload"]["qualification_ratio"] == 1.0


def test_schema_v2_validator_rejects_parent_checksum_mismatch(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)

    manifest_path = output / "manifest.json"
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parent_dataset"]["events_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = DatasetValidator().validate(output)

    assert "parent_dataset_mismatch" in result.error_codes


def test_schema_v2_validator_rejects_untranslated_english_sentence(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="hello there my friend"))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert "non_chinese_text" in result.error_codes
    error = next(item for item in result.errors if item["code"] == "non_chinese_text")
    assert "sequences=0" in error["message"]


def test_schema_v2_validator_accepts_chinese_with_allowlisted_proper_nouns(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="Neuro-sama 今天还会继续玩 Skyrim 吗？"))
    writer.write(_event(1, 60_000, text="这个 NPC 的任务逻辑很奇怪"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_accepts_one_unlisted_proper_noun_in_chinese(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="maimai可爱"))
    writer.write(_event(1, 60_000, text="这个游戏今天还玩吗？"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_accepts_allowlisted_name_adjacent_to_chinese(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="不，Swarm，我们去杀那条吃了Neuro的龙吧"))
    writer.write(_event(1, 60_000, text="这个建议可以继续讨论"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_accepts_allowlisted_multiword_game_term(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="Fus Ro Dah听起来很酷"))
    writer.write(_event(1, 60_000, text="这句龙吼很有气势"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_accepts_reordered_dragon_language_terms(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="聊天区，为什么是VO FUS RO DAH而不是FUS VO DAH？"))
    writer.write(_event(1, 60_000, text="这个龙吼词序值得讨论"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_accepts_two_unlisted_names_in_chinese(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="有人能告诉Vedal，billbill直播好像有问题吗？"))
    writer.write(_event(1, 60_000, text="这个问题需要尽快确认"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_accepts_three_names_in_chinese_dominant_text(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(
        _event(
            0,
            0,
            text="我说得不对吗？Cerly全程照顾她，而Vedal和Filan做了所有工作。",
        ),
    )
    writer.write(_event(1, 60_000, text="这个说法有明确的讨论意图"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_rejects_sparse_chinese_with_three_english_terms(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="这是hello my friend"))
    writer.write(_event(1, 60_000, text="这条是有效中文"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert "non_chinese_text" in result.error_codes


def test_schema_v2_validator_accepts_gps_honorific_term(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="谢谢GPS sama"))
    writer.write(_event(1, 60_000, text="导航这次终于有用了"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_accepts_observed_multiword_character_name(
    tmp_path: Path,
) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0, text="她最后会杀了Party Snax，对吧？（难过）"))
    writer.write(_event(1, 60_000, text="这个预测听起来很危险"))
    writer.finalize(duration_ms=120_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True


def test_schema_v2_validator_rejects_incomplete_synthetic_marker(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-enriched-v2"
    writer = _v2_writer(output, parent, variant="clean-enriched", synthetic_ratio=0.1)
    for sequence in range(10):
        writer.write(_event(sequence, sequence * 5_000))
    writer.write(
        _event(
            10,
            55_000,
            text="这条合成消息没有可见前缀",
            actor_id="synthetic_0001",
            payload={
                "origin": "synthetic",
                "scenario": "direct_question",
                "parent_sequence": 9,
                "intent": "question",
            },
        ),
    )
    writer.finalize(duration_ms=60_000)

    result = DatasetValidator().validate(output)

    assert "invalid_synthetic_marker" in result.error_codes


def test_schema_v2_validator_rejects_synthetic_ratio_mismatch(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-enriched-v2"
    writer = _v2_writer(output, parent, variant="clean-enriched", synthetic_ratio=0.1)
    for sequence in range(10):
        writer.write(_event(sequence, sequence * 5_000))
    for synthetic_index in range(2):
        writer.write(
            _event(
                10 + synthetic_index,
                50_000 + synthetic_index * 1_000,
                text="[合成补充] 你觉得刚才的选择合理吗？",
                actor_id=f"synthetic_{synthetic_index + 1:04d}",
                payload={
                    "origin": "synthetic",
                    "scenario": "direct_question",
                    "parent_sequence": 9,
                    "intent": "question",
                },
            ),
        )
    writer.finalize(duration_ms=60_000)

    result = DatasetValidator().validate(output)

    assert "synthetic_ratio_mismatch" in result.error_codes


def test_schema_v2_validator_accepts_fully_marked_enriched_dataset(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    real_output = tmp_path / "source-clean-real-v2"
    real_writer = _v2_writer(real_output, source)
    for sequence in range(10):
        real_writer.write(_event(sequence, sequence * 5_000))
    parent = real_writer.finalize(duration_ms=60_000)
    output = tmp_path / "source-clean-enriched-v2"
    writer = _v2_writer(output, parent, variant="clean-enriched", synthetic_ratio=0.1)
    for sequence in range(10):
        writer.write(_event(sequence, sequence * 5_000))
    writer.write(
        _event(
            10,
            55_000,
            text="[合成补充] 你觉得刚才的选择合理吗？",
            actor_id="synthetic_0001",
            payload={
                "origin": "synthetic",
                "scenario": "direct_question",
                "parent_sequence": 9,
                "intent": "question",
            },
        ),
    )
    manifest = writer.finalize(duration_ms=60_000)

    result = DatasetValidator().validate(output)

    assert result.valid is True
    assert result.events[-1].actor_id == "synthetic_0001"
    assert manifest["workload"]["rate_p50"] == 10.0
    assert manifest["effective_workload"]["rate_p50"] == 11.0


def test_schema_v2_validator_rejects_non_whitelisted_payload_key(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)
    rows = [
        json.loads(line)
        for line in (output / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["payload"]["raw_payload"] = {"comment_id": "secret"}
    _rewrite_events(output, rows)

    result = DatasetValidator().validate(output)

    assert "payload_not_whitelisted" in result.error_codes


def test_schema_v2_validator_rejects_missing_real_provenance(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)
    rows = [
        json.loads(line)
        for line in (output / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["payload"] = {"source_sequence": "0", "intent": ""}
    _rewrite_events(output, rows)

    result = DatasetValidator().validate(output)

    assert "invalid_real_provenance" in result.error_codes


def test_schema_v2_validator_rejects_banned_manifest_source_key(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["processing"]["vod_id"] = "forbidden"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = DatasetValidator().validate(output)

    assert "privacy_violation" in result.error_codes


def test_schema_v2_validator_rejects_declared_workload_mismatch(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workload"]["rate_p95"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = DatasetValidator().validate(output)

    assert "workload_mismatch" in result.error_codes


def test_schema_v2_validator_rejects_effective_workload_mismatch(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["effective_workload"]["window_count"] = 999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = DatasetValidator().validate(output)

    assert "effective_workload_mismatch" in result.error_codes


def test_schema_v2_validator_rejects_cleaning_count_mismatch(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cleaning_counts"]["retained"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = DatasetValidator().validate(output)

    assert "cleaning_counts_mismatch" in result.error_codes


def test_schema_v2_validator_rejects_incomplete_processing_metadata(tmp_path: Path) -> None:
    parent = _write_source(tmp_path / "source")
    output = tmp_path / "source-clean-real-v2"
    writer = _v2_writer(output, parent)
    writer.write(_event(0, 0))
    writer.write(_event(1, 60_000))
    writer.finalize(duration_ms=120_000)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["processing"]["prompt_version"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = DatasetValidator().validate(output)

    assert "invalid_processing" in result.error_codes
