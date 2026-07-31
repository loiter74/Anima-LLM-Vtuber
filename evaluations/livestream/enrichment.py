"""Deterministic real workload derivation and synthetic scenario enrichment."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType

_REPLYABLE_TYPES = {
    LivestreamEventType.DANMAKU,
    LivestreamEventType.GIFT,
    LivestreamEventType.SUPER_CHAT,
}
_DANMAKU_SCENARIOS = (
    (
        "direct_question",
        "question",
        "你觉得刚才这个选择最关键的理由是什么？",
    ),
    (
        "context_followup",
        "context_followup",
        "那刚才这个选择会影响后面的剧情吗？",
    ),
    (
        "correction_challenge",
        "correction",
        "等等，刚才的判断会不会漏掉了一个条件？",
    ),
    (
        "topic_switch",
        "topic_switch",
        "换个话题，你最近最想挑战什么新内容？",
    ),
    (
        "emotional_support",
        "emotion",
        "别着急，慢慢来，我们都在陪着你。",
    ),
    (
        "safety_privacy_boundary",
        "safety_boundary",
        "不用透露私人信息，说说你方便分享的部分就好。",
    ),
)


def rolling_window_rates(
    events: list[LivestreamEvent],
    *,
    duration_ms: int,
) -> list[int]:
    """Return real replyable counts for every one-second-stepped 60-second window."""
    offsets = [
        event.offset_ms
        for event in events
        if event.event_type in _REPLYABLE_TYPES
        and event.payload.get("origin", "real") != "synthetic"
    ]
    starts = list(range(0, max(0, duration_ms - 60_000) + 1, 1_000)) or [0]
    return [
        sum(start <= offset < min(duration_ms, start + 60_000) for offset in offsets)
        for start in starts
    ]


def derive_high_events(
    events: list[LivestreamEvent],
    *,
    duration_ms: int,
    min_duration_ms: int = 3_600_000,
    max_compression: float = 2.0,
    compression_step: float = 0.05,
) -> tuple[list[LivestreamEvent], int, float]:
    """Compress one continuous real timeline by the minimum factor that qualifies as high."""
    replyable = [event for event in events if event.event_type in _REPLYABLE_TYPES]
    if not replyable:
        raise ValueError("high derivation requires replyable real events")
    if any(
        event.payload.get("origin") == "synthetic" or event.actor_id.startswith("synthetic_")
        for event in replyable
    ):
        raise ValueError("high derivation requires real-only input")
    if min_duration_ms < 60_000 or duration_ms < min_duration_ms:
        raise ValueError("high derivation requires a valid minimum duration")
    if max_compression < 1.0 or compression_step <= 0:
        raise ValueError("high derivation compression settings are invalid")

    maximum = min(max_compression, duration_ms / min_duration_ms)
    step_hundredths = round(compression_step * 100)
    maximum_hundredths = math.floor(maximum * 100 + 1e-9)
    for factor_hundredths in range(100, maximum_hundredths + 1, step_hundredths):
        factor = factor_hundredths / 100
        derived_duration_ms = round(duration_ms / factor)
        derived = [
            LivestreamEvent(
                sequence=index,
                offset_ms=round(event.offset_ms / factor),
                event_type=event.event_type,
                actor_id=event.actor_id,
                text=event.text,
                payload=dict(event.payload),
            )
            for index, event in enumerate(events)
        ]
        rates = rolling_window_rates(derived, duration_ms=derived_duration_ms)
        qualification = sum(61 <= rate <= 300 for rate in rates) / len(rates)
        if qualification >= 0.8:
            return derived, derived_duration_ms, factor
    raise ValueError("real messages cannot satisfy the high heat rolling-window qualification")


def derive_medium_events(
    events: list[LivestreamEvent],
    *,
    duration_ms: int,
    target_rate: int = 40,
    seed: int = 20260717,
) -> list[LivestreamEvent]:
    """Select only real source events into a deterministic medium workload."""
    if not 11 <= target_rate <= 60:
        raise ValueError("medium target rate must be between 11 and 60")
    replyable = [event for event in events if event.event_type in _REPLYABLE_TYPES]
    if any(
        event.payload.get("origin") == "synthetic" or event.actor_id.startswith("synthetic_")
        for event in replyable
    ):
        raise ValueError("medium derivation requires real-only input")

    by_minute: dict[int, list[LivestreamEvent]] = defaultdict(list)
    for event in replyable:
        by_minute[event.offset_ms // 60_000].append(event)

    selected: list[LivestreamEvent] = []
    minute_count = max(1, math.ceil(duration_ms / 60_000))
    for minute in range(minute_count):
        candidates = sorted(
            by_minute.get(minute, []), key=lambda event: (event.offset_ms, event.sequence)
        )
        if len(candidates) <= target_rate:
            selected.extend(candidates)
            continue
        selected.extend(
            _select_minute(candidates, minute=minute, target_rate=target_rate, seed=seed)
        )

    non_replyable = [event for event in events if event.event_type not in _REPLYABLE_TYPES]
    combined = sorted(
        [*selected, *non_replyable], key=lambda event: (event.offset_ms, event.sequence)
    )
    derived = [
        LivestreamEvent(
            sequence=index,
            offset_ms=event.offset_ms,
            event_type=event.event_type,
            actor_id=event.actor_id,
            text=event.text,
            payload=dict(event.payload),
        )
        for index, event in enumerate(combined)
    ]
    rates = rolling_window_rates(derived, duration_ms=duration_ms)
    qualification = sum(11 <= rate <= 60 for rate in rates) / len(rates)
    if max(rates) > 60 or qualification < 0.8:
        raise ValueError(
            "real messages cannot satisfy the medium heat rolling-window qualification",
        )
    return derived


def enrich_scenarios(
    events: list[LivestreamEvent],
    *,
    synthetic_ratio: float = 0.10,
    seed: int = 20260717,
) -> list[LivestreamEvent]:
    """Insert deterministic, visibly marked Chinese test scenarios near real parents."""
    if synthetic_ratio <= 0:
        raise ValueError("synthetic_ratio must be positive")
    real_replyable = [event for event in events if event.event_type in _REPLYABLE_TYPES]
    if not real_replyable:
        raise ValueError("scenario enrichment requires replyable real events")
    if any(
        event.payload.get("origin") == "synthetic" or event.actor_id.startswith("synthetic_")
        for event in real_replyable
    ):
        raise ValueError("scenario enrichment requires real-only input")

    synthetic_total = math.ceil(len(real_replyable) * synthetic_ratio)
    monetary_total = min(
        synthetic_total,
        min(30, max(6, round(len(real_replyable) * 0.01))),
    )
    gift_total = math.ceil(monetary_total * 2 / 3)
    super_chat_total = monetary_total - gift_total
    event_types = _synthetic_event_types(
        synthetic_total,
        gift_total=gift_total,
        super_chat_total=super_chat_total,
        seed=seed,
    )

    synthetic: list[LivestreamEvent] = []
    danmaku_index = 0
    for index, event_type in enumerate(event_types, start=1):
        parent_index = min(
            len(real_replyable) - 1,
            math.floor((index - 0.5) * len(real_replyable) / synthetic_total),
        )
        parent = real_replyable[parent_index]
        if event_type is LivestreamEventType.GIFT:
            scenario = "gift_acknowledgement"
            intent = "gift_support"
            content = "送出星光花束，想为刚才的精彩表现加油！"
            extra_payload: dict[str, object] = {"gift_name": "星光花束", "gift_num": 1}
        elif event_type is LivestreamEventType.SUPER_CHAT:
            scenario = "super_chat_priority"
            intent = "priority_question"
            content = "这条醒目留言想问：接下来最优先准备什么？"
            extra_payload = {"price": 30}
        else:
            scenario, intent, content = _DANMAKU_SCENARIOS[danmaku_index % len(_DANMAKU_SCENARIOS)]
            danmaku_index += 1
            extra_payload = {}
        synthetic.append(
            LivestreamEvent(
                sequence=len(events) + index,
                offset_ms=parent.offset_ms + 1,
                event_type=event_type,
                actor_id=f"synthetic_{index:04d}",
                text=f"[合成补充]{content}",
                payload={
                    "origin": "synthetic",
                    "intent": intent,
                    "scenario": scenario,
                    "parent_sequence": parent.sequence,
                    **extra_payload,
                },
            ),
        )

    combined = sorted(
        [*events, *synthetic],
        key=lambda event: (event.offset_ms, event.sequence),
    )
    parent_sequences = {
        event.sequence: index
        for index, event in enumerate(combined)
        if event.payload.get("origin", "real") != "synthetic"
    }
    result: list[LivestreamEvent] = []
    for index, event in enumerate(combined):
        payload = dict(event.payload)
        if payload.get("origin") == "synthetic":
            payload["parent_sequence"] = parent_sequences[int(payload["parent_sequence"])]
        result.append(
            LivestreamEvent(
                sequence=index,
                offset_ms=event.offset_ms,
                event_type=event.event_type,
                actor_id=event.actor_id,
                text=event.text,
                payload=payload,
            ),
        )
    return result


def _synthetic_event_types(
    total: int,
    *,
    gift_total: int,
    super_chat_total: int,
    seed: int,
) -> list[LivestreamEventType]:
    monetary_total = gift_total + super_chat_total
    monetary_positions = {
        min(total - 1, math.floor((index + 0.5) * total / monetary_total))
        for index in range(monetary_total)
    }
    while len(monetary_positions) < monetary_total:
        monetary_positions.add(
            next(index for index in range(total) if index not in monetary_positions),
        )
    result = [LivestreamEventType.DANMAKU] * total
    gifts_left = gift_total
    super_chats_left = super_chat_total
    for ordinal, position in enumerate(sorted(monetary_positions)):
        prefer_super_chat = (ordinal + seed) % 3 == 2
        if prefer_super_chat and super_chats_left:
            result[position] = LivestreamEventType.SUPER_CHAT
            super_chats_left -= 1
        elif gifts_left:
            result[position] = LivestreamEventType.GIFT
            gifts_left -= 1
        else:
            result[position] = LivestreamEventType.SUPER_CHAT
            super_chats_left -= 1
    return result


def _select_minute(
    candidates: list[LivestreamEvent],
    *,
    minute: int,
    target_rate: int,
    seed: int,
) -> list[LivestreamEvent]:
    remaining = list(candidates)
    selected: list[LivestreamEvent] = []
    actor_counts: Counter[str] = Counter()
    intent_counts: Counter[str] = Counter()
    minute_start = minute * 60_000
    slot_width = 60_000 / target_rate
    for slot in range(target_rate):
        target_offset = minute_start + round((slot + 0.5) * slot_width)

        def rank(event: LivestreamEvent) -> tuple[int, int, int, int, str]:
            intent = str(event.payload.get("intent", "unknown"))
            distance = abs(event.offset_ms - target_offset)
            digest = hashlib.sha256(
                f"{seed}:{minute}:{slot}:{event.sequence}".encode(),
            ).hexdigest()
            return (
                int(distance // slot_width),
                actor_counts[event.actor_id],
                intent_counts[intent],
                distance,
                digest,
            )

        chosen = min(remaining, key=rank)
        remaining.remove(chosen)
        selected.append(chosen)
        actor_counts[chosen.actor_id] += 1
        intent_counts[str(chosen.payload.get("intent", "unknown"))] += 1
    return selected
