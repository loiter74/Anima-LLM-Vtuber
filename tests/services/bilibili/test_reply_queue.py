from __future__ import annotations

import asyncio

import pytest

from animetta.config import ReplyPolicyConfig
from animetta.services.bilibili.models import DanmakuMessage
from animetta.services.bilibili.reply_admission import ReplyPriority
from animetta.services.bilibili.reply_media import (
    OrderedReplyMediaCoordinator,
    ReplyMediaTurn,
)
from animetta.services.bilibili.reply_queue import (
    BoundedReplyQueue,
    DanmakuReplyRuntime,
    ReplyCandidate,
    ReplyMetrics,
    ReplyWorker,
)


def _candidate(
    text: str,
    priority: ReplyPriority,
    *,
    generation: int = 1,
    timestamp: float = 100.0,
) -> ReplyCandidate:
    return ReplyCandidate(
        message=DanmakuMessage(text=text, timestamp=timestamp),
        priority=priority,
        generation_id=generation,
        admitted_at=timestamp,
    )


@pytest.mark.asyncio
async def test_priority_ordering_is_fifo_within_each_priority() -> None:
    queue = BoundedReplyQueue(max_size=5)
    ordinary_one = _candidate("ordinary-1", ReplyPriority.ORDINARY)
    question_one = _candidate("question-1", ReplyPriority.QUESTION)
    ordinary_two = _candidate("ordinary-2", ReplyPriority.ORDINARY)
    question_two = _candidate("question-2", ReplyPriority.QUESTION)

    for candidate in (ordinary_one, question_one, ordinary_two, question_two):
        assert (await queue.put(candidate)).accepted

    assert await queue.get() is question_one
    assert await queue.get() is question_two
    assert await queue.get() is ordinary_one
    assert await queue.get() is ordinary_two


@pytest.mark.asyncio
async def test_higher_priority_evicts_oldest_lower_priority_at_capacity() -> None:
    queue = BoundedReplyQueue(max_size=2)
    oldest = _candidate("oldest", ReplyPriority.ORDINARY)
    newest = _candidate("newest", ReplyPriority.ORDINARY)
    high = _candidate("high", ReplyPriority.SUPER_CHAT)
    await queue.put(oldest)
    await queue.put(newest)

    result = await queue.put(high)

    assert result.accepted is True
    assert result.evicted is oldest
    assert result.reason == "evicted_lower_priority"
    assert await queue.get() is high
    assert await queue.get() is newest


@pytest.mark.asyncio
async def test_full_queue_rejects_equal_or_lower_priority() -> None:
    queue = BoundedReplyQueue(max_size=1)
    await queue.put(_candidate("existing", ReplyPriority.GIFT))

    result = await queue.put(_candidate("new", ReplyPriority.GIFT))

    assert result.accepted is False
    assert result.reason == "queue_full"
    assert queue.qsize == 1


@pytest.mark.asyncio
async def test_generation_discard_removes_only_stale_items() -> None:
    queue = BoundedReplyQueue(max_size=4)
    await queue.put(_candidate("old-1", ReplyPriority.QUESTION, generation=1))
    await queue.put(_candidate("new", ReplyPriority.QUESTION, generation=2))
    await queue.put(_candidate("old-2", ReplyPriority.ORDINARY, generation=1))

    removed = await queue.discard_except_generation(2)

    assert removed == 2
    assert queue.qsize == 1
    assert (await queue.get()).message.text == "new"


@pytest.mark.asyncio
async def test_worker_drops_expired_and_isolates_reply_failures() -> None:
    queue = BoundedReplyQueue(max_size=4)
    metrics = ReplyMetrics()
    processed: list[str] = []

    async def processor(candidate: ReplyCandidate) -> None:
        processed.append(candidate.message.text)
        if candidate.message.text == "fails":
            raise RuntimeError("synthetic failure")

    await queue.put(
        _candidate("expired", ReplyPriority.SUPER_CHAT, timestamp=80),
    )
    await queue.put(_candidate("fails", ReplyPriority.GIFT))
    await queue.put(_candidate("succeeds", ReplyPriority.QUESTION))
    worker = ReplyWorker(
        queue=queue,
        processor=processor,
        metrics=metrics,
        generation_id=1,
        max_message_age_seconds=10,
        clock=lambda: 100.0,
    )

    task = asyncio.create_task(worker.run())
    for _ in range(20):
        if metrics.reply_success == 1:
            break
        await asyncio.sleep(0)
    await worker.stop()
    await task

    assert processed == ["fails", "fails", "succeeds"]
    assert metrics.dropped["expired"] == 1
    assert metrics.admitted_dropped["expired"] == 1
    assert metrics.reply_failure == 1
    assert metrics.reply_retries == 1
    assert metrics.reply_success == 1
    assert metrics.queue_depth == 0


@pytest.mark.asyncio
async def test_runtime_same_generation_switch_is_idempotent() -> None:
    release = asyncio.Event()
    started = asyncio.Event()

    async def processor(_candidate: ReplyCandidate) -> None:
        started.set()
        await release.wait()

    runtime = DanmakuReplyRuntime(
        ReplyPolicyConfig(
            ordinary_sample_rate=1.0,
            per_user_cooldown_seconds=0,
            duplicate_window_seconds=0,
        ),
        processor,
    )
    await runtime.switch_generation(4)
    await runtime.submit(DanmakuMessage(text="hello"), room_id=1, generation_id=4)
    await started.wait()

    await runtime.switch_generation(4)

    assert runtime.worker_running is True
    release.set()
    for _ in range(20):
        if runtime.metrics.reply_success == 1:
            break
        await asyncio.sleep(0)
    assert runtime.metrics.reply_success == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_counts_processor_failure_and_continues() -> None:
    processed: list[str] = []

    async def processor(candidate: ReplyCandidate) -> None:
        processed.append(candidate.message.text)
        if candidate.message.text == "bad":
            raise RuntimeError("synthetic")

    runtime = DanmakuReplyRuntime(
        ReplyPolicyConfig(
            ordinary_sample_rate=1.0,
            per_user_cooldown_seconds=0,
            duplicate_window_seconds=0,
        ),
        processor,
    )
    await runtime.switch_generation(1)
    for text in ("bad", "good"):
        await runtime.submit(
            DanmakuMessage(text=text, user_id=text),
            room_id=7,
            generation_id=1,
        )
    for _ in range(30):
        if runtime.metrics.reply_success == 1:
            break
        await asyncio.sleep(0)

    assert processed == ["bad", "bad", "good"]
    assert runtime.metrics.reply_retries == 1
    assert runtime.metrics.reply_failure == 1
    assert runtime.metrics.reply_success == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_exhaustive_runtime_waits_for_capacity_and_completes_ten_replies() -> None:
    release = asyncio.Event()
    started = asyncio.Event()
    processed: list[str] = []

    async def processor(candidate: ReplyCandidate) -> None:
        processed.append(candidate.message.text)
        started.set()
        await release.wait()

    runtime = DanmakuReplyRuntime(
        ReplyPolicyConfig(mode="exhaustive", max_queue_size=2, generation_concurrency=2),
        processor,
    )
    await runtime.switch_generation(1)
    submissions = [
        asyncio.create_task(
            runtime.submit(
                DanmakuMessage(text=f"m{index}", user_id=7),
                room_id=7,
                generation_id=1,
            )
        )
        for index in range(10)
    ]
    await started.wait()
    release.set()
    results = await asyncio.gather(*submissions)
    for _ in range(50):
        if runtime.metrics.reply_success == 10:
            break
        await asyncio.sleep(0)

    assert all(result.admitted for result in results)
    assert processed == [f"m{index}" for index in range(10)]
    assert runtime.metrics.reply_success == 10
    assert runtime.metrics.admitted_dropped == {}
    assert runtime.metrics.max_queue_depth <= 2
    await runtime.close()


@pytest.mark.asyncio
async def test_ordered_media_turns_wait_for_earlier_generation_and_skip_cancelled_turns() -> None:
    coordinator = OrderedReplyMediaCoordinator()
    first = ReplyMediaTurn(coordinator, 0)
    second = ReplyMediaTurn(coordinator, 1)
    third = ReplyMediaTurn(coordinator, 2)
    second_acquired = asyncio.Event()
    third_acquired = asyncio.Event()

    async def acquire_second() -> None:
        await second.acquire()
        second_acquired.set()

    async def acquire_third() -> None:
        await third.acquire()
        third_acquired.set()

    await first.acquire()
    second_task = asyncio.create_task(acquire_second())
    third_task = asyncio.create_task(acquire_third())
    await asyncio.sleep(0)
    assert second_acquired.is_set() is False
    assert third_acquired.is_set() is False

    await second.cancel()
    await first.finish()
    await asyncio.sleep(0)

    assert third_acquired.is_set() is True
    await third.finish()
    await second_task
    await third_task


@pytest.mark.asyncio
async def test_runtime_returns_auditable_admission_results_and_max_depth() -> None:
    release = asyncio.Event()

    async def processor(_candidate: ReplyCandidate) -> None:
        await release.wait()

    runtime = DanmakuReplyRuntime(
        ReplyPolicyConfig(
            ordinary_sample_rate=1.0,
            per_user_cooldown_seconds=0,
            duplicate_window_seconds=60,
            max_queue_size=2,
        ),
        processor,
    )
    await runtime.switch_generation(1)

    admitted = await runtime.submit(
        DanmakuMessage(text="hello", user_id=1),
        room_id=7,
        generation_id=1,
    )
    duplicate = await runtime.submit(
        DanmakuMessage(text="hello", user_id=2),
        room_id=7,
        generation_id=1,
    )

    assert admitted.admitted is True
    assert admitted.reason is None
    assert duplicate.admitted is False
    assert duplicate.reason == "duplicate"
    assert runtime.metrics.max_queue_depth <= 2
    release.set()
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_counts_evicted_admitted_candidate_as_terminal_drop() -> None:
    release = asyncio.Event()

    async def processor(_candidate: ReplyCandidate) -> None:
        await release.wait()

    runtime = DanmakuReplyRuntime(
        ReplyPolicyConfig(
            ordinary_sample_rate=1.0,
            per_user_cooldown_seconds=0,
            duplicate_window_seconds=0,
            max_queue_size=1,
        ),
        processor,
    )
    await runtime.switch_generation(1)

    ordinary = await runtime.submit(
        DanmakuMessage(text="普通弹幕", user_id=1),
        room_id=7,
        generation_id=1,
    )
    super_chat = await runtime.submit(
        DanmakuMessage(text="醒目留言", user_id=2, is_super_chat=True),
        room_id=7,
        generation_id=1,
    )

    assert ordinary.admitted is True
    assert super_chat.admitted is True
    assert super_chat.evicted_lower_priority is True
    assert runtime.metrics.admitted == 2
    assert runtime.metrics.admitted_dropped["queue_evicted"] == 1
    assert runtime.metrics.reply_failure == 0

    release.set()
    for _ in range(20):
        if runtime.metrics.reply_success == 1:
            break
        await asyncio.sleep(0)
    assert runtime.metrics.reply_success == 1
    assert runtime.metrics.terminal_count == runtime.metrics.admitted
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_reports_busy_while_reply_is_queued_or_processing() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def processor(_candidate: ReplyCandidate) -> None:
        started.set()
        await release.wait()

    runtime = DanmakuReplyRuntime(
        ReplyPolicyConfig(
            ordinary_sample_rate=1.0,
            per_user_cooldown_seconds=0,
            duplicate_window_seconds=0,
        ),
        processor,
    )
    await runtime.switch_generation(1)

    result = await runtime.submit(
        DanmakuMessage(text="正在处理", user_id=1),
        room_id=7,
        generation_id=1,
    )
    assert result.admitted is True
    assert runtime.busy is True

    await started.wait()
    assert runtime.busy is True
    release.set()
    for _ in range(20):
        if not runtime.busy:
            break
        await asyncio.sleep(0)
    assert runtime.busy is False
    await runtime.close()
