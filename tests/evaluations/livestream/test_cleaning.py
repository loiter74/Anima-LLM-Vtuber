from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from evaluations.livestream.cleaning import (
    BalancedCleaner,
    DecisionCache,
    SemanticDecision,
    SemanticRequest,
)


def _event(
    sequence: int,
    offset_ms: int,
    text: str,
    *,
    actor_id: str = "viewer_0001",
) -> LivestreamEvent:
    return LivestreamEvent(
        sequence=sequence,
        offset_ms=offset_ms,
        event_type=LivestreamEventType.DANMAKU,
        actor_id=actor_id,
        text=text,
        payload={},
    )


class RejectUnexpectedProcessor:
    async def process_batch(
        self,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]:
        raise AssertionError(f"semantic processor was not expected: {requests!r}")


class RecordingProcessor:
    def __init__(self) -> None:
        self.requests: list[SemanticRequest] = []

    async def process_batch(
        self,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]:
        self.requests.extend(requests)
        return [
            SemanticDecision(
                sequence=request.sequence,
                keep=True,
                intent="context_reply",
                text_zh="你指的是刚才那个选择吗？",
            )
            for request in requests
        ]


class DroppingRecordingProcessor(RecordingProcessor):
    async def process_batch(
        self,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]:
        self.requests.extend(requests)
        return [
            SemanticDecision(
                sequence=request.sequence,
                keep=False,
                intent="",
                text_zh="",
                reason="unrecognized_intent",
            )
            for request in requests
        ]


class ConcurrencyRecordingProcessor:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def process_batch(
        self,
        requests: list[SemanticRequest],
    ) -> list[SemanticDecision]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return [
            SemanticDecision(
                sequence=request.sequence,
                keep=True,
                intent="opinion",
                text_zh=f"第 {request.sequence} 条中文弹幕",
            )
            for request in requests
        ]


async def test_balanced_cleaner_drops_deterministic_noise_with_stable_reasons() -> None:
    cleaner = BalancedCleaner(processor=RejectUnexpectedProcessor())
    events = [
        _event(0, 0, "???"),
        _event(1, 1_000, "哈哈哈哈"),
        _event(2, 2_000, "KEKW"),
        _event(3, 3_000, "o7"),
        _event(4, 4_000, "o7 bugged"),
        _event(5, 5_000, "这也太离谱了"),
    ]

    result = await cleaner.clean(events)

    assert [event.text for event in result.events] == ["这也太离谱了"]
    assert [drop.reason for drop in result.drops] == [
        "symbol_only",
        "laughter_only",
        "emote_only",
        "meaningless_abbreviation",
        "meaningless_abbreviation",
    ]
    assert all(drop.text_hash and len(drop.text_hash) == 64 for drop in result.drops)


async def test_balanced_cleaner_drops_observed_neuro_emotes_and_chants() -> None:
    cleaner = BalancedCleaner(processor=RejectUnexpectedProcessor())
    events = [
        _event(0, 0, "LULE"),
        _event(1, 1_000, "Tutel"),
        _event(2, 2_000, "vedal eliv"),
        _event(3, 3_000, "NeuroJAM"),
        _event(4, 4_000, "tutelBedge"),
        _event(5, 5_000, "xdd"),
        _event(6, 6_000, "VedalIssues ?"),
    ]

    result = await cleaner.clean(events)

    assert result.events == []
    assert [drop.reason for drop in result.drops] == ["emote_only"] * 7


async def test_balanced_cleaner_preserves_clear_intents_without_llm() -> None:
    cleaner = BalancedCleaner(processor=RejectUnexpectedProcessor())
    events = [
        _event(0, 0, "你为什么选这个技能？"),
        _event(1, 10_000, "快去左边打开宝箱", actor_id="viewer_0002"),
        _event(2, 20_000, "晚上好，第一次来看直播", actor_id="viewer_0003"),
        _event(3, 30_000, "这个角色的设定很有意思", actor_id="viewer_0004"),
    ]

    result = await cleaner.clean(events)

    assert [event.payload["intent"] for event in result.events] == [
        "question",
        "game_instruction",
        "greeting",
        "opinion",
    ]
    assert all(event.payload["origin"] == "real" for event in result.events)
    assert [event.payload["source_sequence"] for event in result.events] == [0, 1, 2, 3]


async def test_balanced_cleaner_routes_chinese_fragment_without_intent_to_semantic_drop() -> None:
    processor = DroppingRecordingProcessor()
    cleaner = BalancedCleaner(processor=processor)
    events = [
        _event(0, 0, "这个角色的设定很有意思"),
        _event(1, 5_000, "的的的", actor_id="viewer_0002"),
    ]

    result = await cleaner.clean(events)

    assert [request.sequence for request in processor.requests] == [1]
    assert [item.sequence for item in processor.requests[0].context_before] == [0]
    assert [event.payload["source_sequence"] for event in result.events] == [0]
    assert [drop.reason for drop in result.drops] == ["unrecognized_intent"]


async def test_balanced_cleaner_drops_same_actor_duplicate_within_thirty_seconds() -> None:
    cleaner = BalancedCleaner(processor=RejectUnexpectedProcessor())
    events = [
        _event(0, 0, "左边有一个宝箱"),
        _event(1, 20_000, " 左边有一个宝箱！ "),
        _event(2, 40_000, "左边有一个宝箱"),
    ]

    result = await cleaner.clean(events)

    assert [event.payload["source_sequence"] for event in result.events] == [0, 2]
    assert [drop.reason for drop in result.drops] == ["same_actor_duplicate"]


async def test_balanced_cleaner_keeps_same_reaction_from_different_actors() -> None:
    cleaner = BalancedCleaner(processor=RejectUnexpectedProcessor())
    events = [
        _event(0, 0, "这也太离谱了", actor_id="viewer_0001"),
        _event(1, 1_000, "这也太离谱了", actor_id="viewer_0002"),
    ]

    result = await cleaner.clean(events)

    assert len(result.events) == 2
    assert result.drops == []


async def test_balanced_cleaner_sends_ambiguous_foreign_message_with_bounded_context() -> None:
    processor = RecordingProcessor()
    cleaner = BalancedCleaner(processor=processor)
    events = [
        _event(0, 0, "刚才应该走左边", actor_id="viewer_0001"),
        _event(1, 5_000, "that one?", actor_id="viewer_0002"),
        _event(2, 10_000, "然后再打开宝箱", actor_id="viewer_0003"),
        _event(3, 40_000, "这条消息超出上下文窗口", actor_id="viewer_0004"),
    ]

    result = await cleaner.clean(events)

    assert len(processor.requests) == 1
    request = processor.requests[0]
    assert request.sequence == 1
    assert [item.sequence for item in request.context_before] == [0]
    assert [item.sequence for item in request.context_after] == [2]
    translated = next(event for event in result.events if event.payload["source_sequence"] == 1)
    assert translated.text == "你指的是刚才那个选择吗？"
    assert result.translated_count == 1


async def test_balanced_cleaner_localizes_mixed_text_that_is_not_chinese_dominant() -> None:
    processor = RecordingProcessor()
    cleaner = BalancedCleaner(processor=processor)
    event = _event(
        0,
        0,
        "这个说明 still contains a complete untranslated English sentence here",
    )

    result = await cleaner.clean([event])

    assert [request.sequence for request in processor.requests] == [0]
    assert result.events[0].text == "你指的是刚才那个选择吗？"
    assert result.translated_count == 1


async def test_balanced_cleaner_collapses_long_cross_actor_copypasta() -> None:
    cleaner = BalancedCleaner(processor=RejectUnexpectedProcessor())
    repeated = "这个超长复制内容没有增加新的互动信息，只是在不同账号之间连续重复刷屏"
    events = [
        _event(0, 0, repeated, actor_id="viewer_0001"),
        _event(1, 2_000, repeated, actor_id="viewer_0002"),
        _event(2, 4_000, repeated, actor_id="viewer_0003"),
    ]

    result = await cleaner.clean(events)

    assert [event.payload["source_sequence"] for event in result.events] == [0]
    assert [drop.reason for drop in result.drops] == ["copypasta", "copypasta"]


async def test_decision_cache_reuses_hash_key_without_storing_source_text(tmp_path: Path) -> None:
    cache_path = tmp_path / "semantic-decisions.jsonl"
    source_checksum = "a" * 64
    processor = RecordingProcessor()
    event = _event(7, 5_000, "that one?", actor_id="viewer_0002")

    first = await BalancedCleaner(
        processor=processor,
        cache=DecisionCache(cache_path, source_checksum=source_checksum),
    ).clean([event])
    second = await BalancedCleaner(
        processor=RejectUnexpectedProcessor(),
        cache=DecisionCache(cache_path, source_checksum=source_checksum),
    ).clean([event])

    cache_text = cache_path.read_text(encoding="utf-8")
    assert len(processor.requests) == 1
    assert first.events[0].text == second.events[0].text == "你指的是刚才那个选择吗？"
    assert "that one?" not in cache_text
    assert source_checksum in cache_text
    assert '"text_hash"' in cache_text
    assert "你指的是刚才那个选择吗？" in cache_text


async def test_cached_decisions_receive_current_embedded_term_normalization(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "semantic-decisions.jsonl"
    cache = DecisionCache(cache_path, source_checksum="c" * 64)
    events = [
        _event(39, 1_000, "nwero DUM ?", actor_id="viewer_0001"),
        _event(2684, 2_000, "Nice vedalOk", actor_id="viewer_0002"),
        _event(2957, 3_000, "Oh well o7", actor_id="viewer_0003"),
    ]
    cached_texts = ("nwero 笨？", "好，vedalOk", "唉，o7。")
    for event, text_zh in zip(events, cached_texts, strict=True):
        cache.put(
            event,
            SemanticDecision(
                sequence=event.sequence,
                keep=True,
                intent="reaction",
                text_zh=text_zh,
            ),
        )

    result = await BalancedCleaner(
        processor=RejectUnexpectedProcessor(),
        cache=DecisionCache(cache_path, source_checksum="c" * 64),
    ).clean(events)

    assert [event.text for event in result.events] == [
        "Neuro 笨？",
        "好，（赞同）",
        "唉，（敬礼）。",
    ]


async def test_decision_cache_checkpoints_successful_batches_before_a_later_failure(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "semantic-decisions.jsonl"
    source_checksum = "b" * 64
    events = [
        _event(0, 0, "first foreign message", actor_id="viewer_0001"),
        _event(1, 1_000, "second foreign message", actor_id="viewer_0002"),
    ]

    class FailingSecondBatchProcessor(RecordingProcessor):
        async def process_batch(
            self,
            requests: list[SemanticRequest],
        ) -> list[SemanticDecision]:
            if requests[0].sequence == 1:
                raise RuntimeError("later batch failed")
            return await super().process_batch(requests)

    with pytest.raises(RuntimeError, match="later batch failed"):
        await BalancedCleaner(
            processor=FailingSecondBatchProcessor(),
            cache=DecisionCache(cache_path, source_checksum=source_checksum),
            batch_size=1,
            max_concurrency=1,
        ).clean(events)

    processor = RecordingProcessor()
    result = await BalancedCleaner(
        processor=processor,
        cache=DecisionCache(cache_path, source_checksum=source_checksum),
        batch_size=1,
        max_concurrency=1,
    ).clean(events)

    assert [request.sequence for request in processor.requests] == [1]
    assert len(result.events) == 2


async def test_balanced_cleaner_limits_semantic_batch_concurrency_to_four() -> None:
    processor = ConcurrencyRecordingProcessor()
    cleaner = BalancedCleaner(
        processor=processor,
        batch_size=1,
        max_concurrency=4,
    )
    events = [
        _event(
            sequence,
            sequence * 1_000,
            f"foreign message {sequence}",
            actor_id=f"viewer_{sequence + 1:04d}",
        )
        for sequence in range(8)
    ]

    result = await cleaner.clean(events)

    assert len(result.events) == 8
    assert processor.max_active == 4
