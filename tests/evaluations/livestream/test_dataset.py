from __future__ import annotations

import json
from pathlib import Path

import pytest

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from evaluations.livestream.dataset import (
    DatasetValidator,
    DatasetWriter,
    EventSanitizer,
    HeatTier,
)


def event(
    sequence: int,
    offset_ms: int,
    event_type: LivestreamEventType = LivestreamEventType.DANMAKU,
    *,
    actor_id: str = "Alice",
    text: str = "hello",
    payload: dict[str, object] | None = None,
) -> LivestreamEvent:
    return LivestreamEvent(
        sequence=sequence,
        offset_ms=offset_ms,
        event_type=event_type,
        actor_id=actor_id,
        text=text,
        payload=payload or {"user_id": 42},
    )


def write_low_heat_dataset(path: Path) -> dict[str, object]:
    writer = DatasetWriter(path, dataset_id="low-a", heat_tier=HeatTier.LOW)
    for sequence in range(4):
        writer.write(event(sequence, sequence * 60_000))
    return writer.finalize(duration_ms=240_000)


def test_actor_alias_is_stable_only_within_one_sanitizer() -> None:
    sanitizer = EventSanitizer()

    first = sanitizer.sanitize(event(0, 0, actor_id="Alice", payload={"user_id": 42}))
    again = sanitizer.sanitize(event(1, 10, actor_id="Alice", payload={"user_id": 42}))
    other = sanitizer.sanitize(event(2, 20, actor_id="Bob", payload={"user_id": 7}))

    assert first.actor_id == again.actor_id == "viewer_0001"
    assert other.actor_id == "viewer_0002"
    assert EventSanitizer().sanitize(event(0, 0, actor_id="Bob")).actor_id == "viewer_0001"


def test_text_sanitization_replaces_identity_and_contact_details() -> None:
    raw = event(
        0,
        0,
        actor_id="Alice",
        text="Alice 邮箱 alice@example.com 手机 13800138000，主页 https://example.com/u/1 @alice",
    )

    clean = EventSanitizer().sanitize(raw)

    assert clean.actor_id == "viewer_0001"
    assert "Alice" not in clean.text
    assert "alice@example.com" not in clean.text
    assert "13800138000" not in clean.text
    assert "https://" not in clean.text
    assert "@alice" not in clean.text
    assert "[邮箱]" in clean.text
    assert "[电话]" in clean.text


@pytest.mark.parametrize(
    ("event_type", "payload", "expected"),
    [
        (LivestreamEventType.DANMAKU, {"user_id": 42, "raw": "secret"}, {}),
        (
            LivestreamEventType.GIFT,
            {"user_id": 42, "gift_name": "星星", "gift_num": 2, "raw": "secret"},
            {"gift_name": "星星", "gift_num": 2},
        ),
        (LivestreamEventType.SUPER_CHAT, {"user_id": 42, "price": 30}, {"price": 30}),
        (LivestreamEventType.LIKE_BATCH, {"user_id": 42, "count": 9}, {"count": 9}),
        (
            LivestreamEventType.POPULARITY_SNAPSHOT,
            {"popularity": 123, "room_id": 999},
            {"popularity": 123},
        ),
        (LivestreamEventType.UNKNOWN, {"command": "NEW_CMD", "raw": {}}, {"command": "NEW_CMD"}),
    ],
)
def test_payload_is_whitelisted(
    event_type: LivestreamEventType,
    payload: dict[str, object],
    expected: dict[str, object],
) -> None:
    clean = EventSanitizer().sanitize(event(0, 0, event_type, payload=payload))

    assert clean.payload == expected


def test_writer_creates_jsonl_manifest_checksum_and_statistics(tmp_path: Path) -> None:
    manifest = write_low_heat_dataset(tmp_path / "dataset")

    assert manifest["schema_version"] == 1
    assert manifest["dataset_id"] == "low-a"
    assert manifest["heat_tier"] == "low"
    assert manifest["event_count"] == 4
    assert manifest["event_counts"] == {"danmaku": 4}
    assert len(str(manifest["events_sha256"])) == 64
    assert manifest["sanitizer_version"] == "1"
    assert manifest["workload"]["qualification_ratio"] == 1.0

    events = (tmp_path / "dataset" / "events.jsonl").read_text(encoding="utf-8")
    assert "Alice" not in events
    assert "42" not in events
    assert "viewer_0001" in events


def test_validator_accepts_a_valid_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    write_low_heat_dataset(dataset)

    result = DatasetValidator().validate(dataset)

    assert result.valid is True
    assert result.error_codes == []
    assert len(result.events) == 4


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("schema", "unknown_schema"),
        ("checksum", "checksum_mismatch"),
        ("timeline", "invalid_timeline"),
        ("counts", "event_count_mismatch"),
        ("privacy", "privacy_violation"),
    ],
)
def test_validator_reports_actionable_rejection_reason(
    tmp_path: Path,
    mutation: str,
    error_code: str,
) -> None:
    dataset = tmp_path / mutation
    write_low_heat_dataset(dataset)
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if mutation == "schema":
        manifest["schema_version"] = 999
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mutation == "checksum":
        manifest["events_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif mutation == "timeline":
        lines = (dataset / "events.jsonl").read_text(encoding="utf-8").splitlines()
        payload = json.loads(lines[2])
        payload["offset_ms"] = 1
        lines[2] = json.dumps(payload)
        (dataset / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif mutation == "counts":
        manifest["event_count"] = 9
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        lines = (dataset / "events.jsonl").read_text(encoding="utf-8").splitlines()
        payload = json.loads(lines[0])
        payload["text"] = "call 13800138000"
        lines[0] = json.dumps(payload)
        (dataset / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = DatasetValidator().validate(dataset)

    assert result.valid is False
    assert error_code in result.error_codes


def test_validator_rejects_dataset_that_misses_heat_qualification(tmp_path: Path) -> None:
    dataset = tmp_path / "too-hot"
    writer = DatasetWriter(dataset, dataset_id="bad-low", heat_tier=HeatTier.LOW)
    for sequence in range(12):
        writer.write(event(sequence, sequence * 100))
    writer.finalize(duration_ms=60_000)

    result = DatasetValidator().validate(dataset)

    assert "heat_tier_mismatch" in result.error_codes
    error = next(item for item in result.errors if item["code"] == "heat_tier_mismatch")
    assert "tier=low" in error["message"]
    assert "qualification_ratio=" in error["message"]
