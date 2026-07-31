from __future__ import annotations

import pytest

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from evaluations.livestream.enrichment import (
    derive_high_events,
    derive_medium_events,
    rolling_window_rates,
)


def _high_events(*, minutes: int = 4, per_minute: int = 80) -> list[LivestreamEvent]:
    events: list[LivestreamEvent] = []
    for minute in range(minutes):
        for index in range(per_minute):
            sequence = minute * per_minute + index + 1
            events.append(
                LivestreamEvent(
                    sequence=sequence,
                    offset_ms=minute * 60_000 + index * (60_000 // per_minute),
                    event_type=LivestreamEventType.DANMAKU,
                    actor_id=f"viewer_{index % 12 + 1:04d}",
                    text=f"这局第{sequence}条建议是什么？",
                    payload={
                        "origin": "real",
                        "source_sequence": sequence + 10_000,
                        "intent": ("question", "opinion", "game_instruction")[index % 3],
                    },
                ),
            )
    return events


def test_medium_derivation_is_fixed_seed_real_only_and_preserves_source_fields() -> None:
    source = _high_events()

    first = derive_medium_events(source, duration_ms=240_000, target_rate=40, seed=20260717)
    second = derive_medium_events(source, duration_ms=240_000, target_rate=40, seed=20260717)

    assert [event.to_dict() for event in first] == [event.to_dict() for event in second]
    assert len(first) == 160
    assert [event.sequence for event in first] == list(range(len(first)))
    source_by_sequence = {event.payload["source_sequence"]: event for event in source}
    selected_source_sequences = set()
    for event in first:
        original = source_by_sequence[event.payload["source_sequence"]]
        assert event.offset_ms == original.offset_ms
        assert event.payload["source_sequence"] == original.payload["source_sequence"]
        assert event.payload["origin"] == "real"
        assert not event.actor_id.startswith("synthetic_")
        selected_source_sequences.add(event.payload["source_sequence"])
    assert len(selected_source_sequences) == len(first)


def test_medium_derivation_meets_true_rolling_window_gate() -> None:
    events = derive_medium_events(
        _high_events(minutes=5),
        duration_ms=300_000,
        target_rate=40,
        seed=20260717,
    )

    rates = rolling_window_rates(events, duration_ms=300_000)

    assert max(rates) <= 60
    assert sum(11 <= rate <= 60 for rate in rates) / len(rates) >= 0.8


def test_medium_derivation_stratifies_intents_and_actors() -> None:
    source = _high_events(minutes=2)

    events = derive_medium_events(source, duration_ms=120_000, target_rate=40, seed=7)

    assert {event.payload["intent"] for event in events} == {
        "question",
        "opinion",
        "game_instruction",
    }
    assert len({event.actor_id for event in events}) >= 10


def test_medium_derivation_fails_when_real_messages_cannot_qualify() -> None:
    sparse = _high_events(minutes=4, per_minute=8)

    with pytest.raises(ValueError, match="medium heat"):
        derive_medium_events(sparse, duration_ms=240_000, target_rate=40, seed=20260717)


def test_medium_derivation_rejects_synthetic_input() -> None:
    source = _high_events(minutes=2)
    synthetic = source[0]
    source[0] = LivestreamEvent(
        sequence=synthetic.sequence,
        offset_ms=synthetic.offset_ms,
        event_type=synthetic.event_type,
        actor_id="synthetic_0001",
        text="[合成补充]这条不应参与中热派生",
        payload={**synthetic.payload, "origin": "synthetic"},
    )

    with pytest.raises(ValueError, match="real-only"):
        derive_medium_events(source, duration_ms=120_000, target_rate=40, seed=20260717)


def test_high_derivation_uses_minimum_qualifying_real_timeline_compression() -> None:
    source = _high_events(minutes=4, per_minute=40)

    events, duration_ms, factor = derive_high_events(
        source,
        duration_ms=240_000,
        min_duration_ms=120_000,
    )

    rates = rolling_window_rates(events, duration_ms=duration_ms)
    qualification = sum(61 <= rate <= 300 for rate in rates) / len(rates)
    assert factor == 1.55
    assert duration_ms >= 120_000
    assert qualification >= 0.8
    assert max(rates) <= 300
    assert [event.payload["source_sequence"] for event in events] == [
        event.payload["source_sequence"] for event in source
    ]
    assert events[-1].offset_ms < source[-1].offset_ms


def test_high_derivation_fails_when_two_x_real_timeline_is_still_sparse() -> None:
    source = _high_events(minutes=4, per_minute=10)

    with pytest.raises(ValueError, match="high heat"):
        derive_high_events(
            source,
            duration_ms=240_000,
            min_duration_ms=120_000,
        )
