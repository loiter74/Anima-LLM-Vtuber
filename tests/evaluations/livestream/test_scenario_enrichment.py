from __future__ import annotations

import hashlib
import json
import math
from collections import Counter

import pytest

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from evaluations.livestream.enrichment import enrich_scenarios


def _real_events(count: int) -> list[LivestreamEvent]:
    intents = ("question", "opinion", "game_instruction", "emotion")
    return [
        LivestreamEvent(
            sequence=index,
            offset_ms=(index - 1) * 1_000,
            event_type=LivestreamEventType.DANMAKU,
            actor_id=f"viewer_{index % 20 + 1:04d}",
            text=f"第{index}条真实中文弹幕想讨论剧情",
            payload={
                "origin": "real",
                "source_sequence": index + 2_000,
                "intent": intents[index % len(intents)],
            },
        )
        for index in range(1, count + 1)
    ]


def _digest(events: list[LivestreamEvent]) -> str:
    payload = "\n".join(
        json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")) for event in events
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def test_enrichment_is_exact_deterministic_and_resequenced() -> None:
    real = _real_events(200)

    first = enrich_scenarios(real, synthetic_ratio=0.10, seed=20260717)
    second = enrich_scenarios(real, synthetic_ratio=0.10, seed=20260717)

    synthetic = [event for event in first if event.payload.get("origin") == "synthetic"]
    assert len(synthetic) == math.ceil(len(real) * 0.10)
    assert _digest(first) == _digest(second)
    assert [event.sequence for event in first] == list(range(len(first)))
    assert [(event.offset_ms, event.sequence) for event in first] == sorted(
        (event.offset_ms, event.sequence) for event in first
    )


def test_enrichment_marks_all_three_provenance_surfaces_and_parent_context() -> None:
    real = _real_events(200)
    enriched = enrich_scenarios(real, synthetic_ratio=0.10, seed=7)
    synthetic = [event for event in enriched if event.payload.get("origin") == "synthetic"]

    assert synthetic
    assert all(event.text.startswith("[合成补充]") for event in synthetic)
    assert [event.actor_id for event in synthetic] == [
        f"synthetic_{index:04d}" for index in range(1, len(synthetic) + 1)
    ]
    real_by_sequence = {
        event.sequence: event for event in enriched if event.payload.get("origin") == "real"
    }
    assert all(event.payload["parent_sequence"] in real_by_sequence for event in synthetic)
    assert all(event.payload["scenario"] and event.payload["intent"] for event in synthetic)
    assert all(
        event.offset_ms >= real_by_sequence[event.payload["parent_sequence"]].offset_ms
        for event in synthetic
    )


def test_enrichment_covers_required_scenarios_and_monetary_split() -> None:
    enriched = enrich_scenarios(_real_events(200), synthetic_ratio=0.10, seed=11)
    synthetic = [event for event in enriched if event.payload.get("origin") == "synthetic"]
    counts = Counter(event.event_type for event in synthetic)

    assert counts == {
        LivestreamEventType.DANMAKU: 14,
        LivestreamEventType.GIFT: 4,
        LivestreamEventType.SUPER_CHAT: 2,
    }
    assert {event.payload["scenario"] for event in synthetic} >= {
        "direct_question",
        "context_followup",
        "correction_challenge",
        "topic_switch",
        "emotional_support",
        "safety_privacy_boundary",
        "gift_acknowledgement",
        "super_chat_priority",
    }
    assert all(
        event.payload.get("gift_name") == "星光花束"
        for event in synthetic
        if event.event_type is LivestreamEventType.GIFT
    )


@pytest.mark.parametrize(
    ("real_count", "expected_total", "expected_monetary"),
    [(101, 11, 6), (4_000, 400, 30)],
)
def test_enrichment_applies_exact_ratio_and_monetary_clamps(
    real_count: int,
    expected_total: int,
    expected_monetary: int,
) -> None:
    enriched = enrich_scenarios(_real_events(real_count), synthetic_ratio=0.10, seed=1)
    synthetic = [event for event in enriched if event.payload.get("origin") == "synthetic"]
    monetary = [
        event
        for event in synthetic
        if event.event_type in {LivestreamEventType.GIFT, LivestreamEventType.SUPER_CHAT}
    ]

    assert len(synthetic) == expected_total
    assert len(monetary) == expected_monetary
    gift_count = sum(event.event_type is LivestreamEventType.GIFT for event in monetary)
    assert gift_count == math.ceil(expected_monetary * 2 / 3)


def test_enrichment_rejects_existing_synthetic_events() -> None:
    real = _real_events(20)
    event = real[0]
    real[0] = LivestreamEvent(
        sequence=event.sequence,
        offset_ms=event.offset_ms,
        event_type=event.event_type,
        actor_id="synthetic_0001",
        text="[合成补充]已有合成内容",
        payload={**event.payload, "origin": "synthetic"},
    )

    with pytest.raises(ValueError, match="real-only"):
        enrich_scenarios(real, synthetic_ratio=0.10, seed=1)
