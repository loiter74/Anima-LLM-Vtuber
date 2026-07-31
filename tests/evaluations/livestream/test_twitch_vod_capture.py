from __future__ import annotations

import json
from pathlib import Path

from evaluations.livestream.dataset import DatasetWriter, HeatTier
from evaluations.livestream.twitch_vod import TwitchVodCollector


def _edge(
    comment_id: str,
    *,
    offset: float,
    actor_id: str,
    actor_login: str,
    text: str,
) -> dict[str, object]:
    return {
        "cursor": f"cursor-{comment_id}",
        "node": {
            "id": comment_id,
            "contentOffsetSeconds": offset,
            "createdAt": "2026-07-19T00:00:00Z",
            "commenter": {"id": actor_id, "login": actor_login, "displayName": actor_login},
            "message": {
                "fragments": [
                    {"text": text, "emote": None},
                    {"text": "!", "emote": {"id": "emote-secret"}},
                ],
            },
            "rawProtocolField": "must-never-persist",
        },
    }


def test_twitch_vod_collector_deduplicates_and_persists_only_relative_sanitized_events(
    tmp_path: Path,
) -> None:
    pages = {
        90: [
            _edge(
                "comment-secret-a",
                offset=90.0,
                actor_id="uid-secret-1",
                actor_login="RawAlice",
                text="hello",
            ),
            _edge(
                "comment-secret-b",
                offset=94.5,
                actor_id="uid-secret-1",
                actor_login="RawAlice",
                text="what happened",
            ),
        ],
        95: [
            _edge(
                "comment-secret-b",
                offset=94.5,
                actor_id="uid-secret-1",
                actor_login="RawAlice",
                text="what happened",
            ),
            _edge(
                "comment-secret-c",
                offset=99.0,
                actor_id="uid-secret-2",
                actor_login="RawBob",
                text="good answer",
            ),
        ],
        100: [],
    }
    requested: list[int] = []

    def fetch_page(offset_seconds: int) -> list[dict[str, object]]:
        requested.append(offset_seconds)
        return pages.get(offset_seconds, [])

    writer = DatasetWriter(tmp_path, dataset_id="high-candidate", heat_tier=HeatTier.HIGH)
    manifest = TwitchVodCollector(
        vod_id="vod-secret-123",
        writer=writer,
        start_seconds=90,
        duration_seconds=10,
        page_step_seconds=5,
        fetch_page=fetch_page,
        max_workers=1,
    ).capture()

    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    serialized = json.dumps(manifest, ensure_ascii=False) + json.dumps(events, ensure_ascii=False)

    assert requested == [90, 95, 100]
    assert [event["sequence"] for event in events] == [0, 1, 2]
    assert [event["offset_ms"] for event in events] == [0, 4500, 9000]
    assert [event["actor_id"] for event in events] == [
        "viewer_0001",
        "viewer_0001",
        "viewer_0002",
    ]
    assert [event["text"] for event in events] == ["hello!", "what happened!", "good answer!"]
    assert manifest["duration_ms"] == 10_000
    assert manifest["event_count"] == 3
    for secret in (
        "vod-secret-123",
        "comment-secret-a",
        "comment-secret-b",
        "comment-secret-c",
        "uid-secret-1",
        "uid-secret-2",
        "RawAlice",
        "RawBob",
        "2026-07-19",
        "rawProtocolField",
        "must-never-persist",
        "emote-secret",
    ):
        assert secret not in serialized


def test_twitch_vod_collector_refines_dense_five_second_pages(tmp_path: Path) -> None:
    dense_page = [
        _edge(
            f"dense-{index}",
            offset=index / 20,
            actor_id=f"actor-{index}",
            actor_login=f"viewer-{index}",
            text=f"message {index}",
        )
        for index in range(59)
    ]
    requested: list[int] = []

    def fetch_page(offset_seconds: int) -> list[dict[str, object]]:
        requested.append(offset_seconds)
        return dense_page if offset_seconds == 0 else []

    writer = DatasetWriter(tmp_path, dataset_id="dense", heat_tier=HeatTier.HIGH)
    TwitchVodCollector(
        vod_id="vod-secret",
        writer=writer,
        start_seconds=0,
        duration_seconds=5,
        page_step_seconds=5,
        fetch_page=fetch_page,
        max_workers=1,
    ).capture()

    assert requested == [0, 5, 1, 2, 3, 4]


def test_twitch_vod_collector_records_deterministic_real_only_rate_shaping(
    tmp_path: Path,
) -> None:
    def fetch_page(offset_seconds: int) -> list[dict[str, object]]:
        if offset_seconds >= 120:
            return []
        return [
            _edge(
                f"comment-{offset_seconds}-{index}",
                offset=offset_seconds + index / 10,
                actor_id=f"actor-{index}",
                actor_login=f"viewer-{index}",
                text=f"meaningful message {index}",
            )
            for index in range(50)
        ]

    writer = DatasetWriter(tmp_path, dataset_id="shaped", heat_tier=HeatTier.HIGH)
    manifest = TwitchVodCollector(
        vod_id="vod-secret",
        writer=writer,
        start_seconds=0,
        duration_seconds=120,
        page_step_seconds=5,
        fetch_page=fetch_page,
        max_workers=1,
        rate_cap_per_minute=120,
    ).capture()
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert manifest["event_count"] == 240
    assert manifest["capture_derivation"] == {
        "kind": "deterministic_real_rate_cap",
        "rate_cap_per_minute": 120,
        "observed_replyable": 1200,
        "selected_replyable": 240,
    }
    assert max(manifest["workload"][key] for key in ("rate_min", "rate_max")) == 120
    assert [event["sequence"] for event in events] == list(range(240))
    assert all(event["payload"]["source_sequence"] >= event["sequence"] for event in events)
    assert all(event["actor_id"].startswith("viewer_") for event in events)
    assert sum(event["offset_ms"] < 1000 for event in events) == 10


def test_twitch_vod_collector_prefilters_only_auditable_deterministic_noise(
    tmp_path: Path,
) -> None:
    page = [
        _edge(
            "noise",
            offset=0,
            actor_id="actor-a",
            actor_login="viewer-a",
            text="kappa",
        ),
        _edge(
            "question",
            offset=1,
            actor_id="actor-b",
            actor_login="viewer-b",
            text="why did that happen?",
        ),
        _edge(
            "opinion",
            offset=2,
            actor_id="actor-c",
            actor_login="viewer-c",
            text="that choice was clever",
        ),
    ]
    writer = DatasetWriter(tmp_path, dataset_id="prefiltered", heat_tier=HeatTier.HIGH)
    manifest = TwitchVodCollector(
        vod_id="vod-secret",
        writer=writer,
        start_seconds=0,
        duration_seconds=5,
        page_step_seconds=5,
        fetch_page=lambda offset: page if offset == 0 else [],
        max_workers=1,
        deterministic_prefilter=True,
    ).capture()
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert [event["text"] for event in events] == [
        "why did that happen?!",
        "that choice was clever!",
    ]
    assert [event["payload"]["source_sequence"] for event in events] == [1, 2]
    assert manifest["capture_derivation"] == {
        "kind": "deterministic_real_quality_selection",
        "deterministic_prefilter": True,
        "observed_replyable": 3,
        "eligible_replyable": 2,
        "selected_replyable": 2,
    }
