"""Deterministic scheduling and source contracts for proactive topics."""

from __future__ import annotations

import asyncio
from collections import deque

from animetta.config.proactive_topics import ProactiveTopicsConfig
from animetta.services.bilibili.proactive_topics import (
    DeadpanLogicSource,
    ProactiveTopicRuntime,
    SceneTopicSource,
    TopicContext,
    TopicSeed,
)
from animetta.services.scene_analysis.models import LiveSceneState, TopicState, Trend


class ControlledSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []
        self._waiters: deque[asyncio.Future[None]] = deque()

    async def __call__(self, delay: float) -> None:
        waiter = asyncio.get_running_loop().create_future()
        self.delays.append(delay)
        self._waiters.append(waiter)
        await waiter

    async def release(self) -> None:
        await _settle()
        self._waiters.popleft().set_result(None)
        await _settle()


async def _settle() -> None:
    for _ in range(4):
        await asyncio.sleep(0)


def _live_status(*, room_id: int = 42, generation_id: int = 7) -> dict[str, object]:
    return {
        "state": "live",
        "room_id": room_id,
        "generation_id": generation_id,
    }


def _scene() -> LiveSceneState:
    return LiveSceneState.initial(
        session_id="live-42-7",
        room_id=42,
        generation_id=7,
        now=1,
    ).model_copy(
        update={
            "topics": [
                TopicState(label="旧话题", heat=0.7, trend=Trend.FALLING, last_event_seq=2),
                TopicState(label="热话题", heat=0.9, trend=Trend.RISING, last_event_seq=3),
            ]
        }
    )


async def test_scene_source_selects_hottest_unused_topic_then_falls_back() -> None:
    source = SceneTopicSource()
    context = TopicContext(scene=_scene(), used_dedupe_keys=frozenset(), recent_outputs=())

    first = await source.next_seed(context)
    assert first == TopicSeed(
        kind="scene",
        subject="热话题",
        dedupe_key="scene:热话题:3",
        provenance="scene_runtime",
    )

    exhausted = TopicContext(
        scene=_scene(),
        used_dedupe_keys=frozenset({"scene:旧话题:2", "scene:热话题:3"}),
        recent_outputs=(),
    )
    assert await source.next_seed(exhausted) is None
    assert (await DeadpanLogicSource().next_seed(exhausted)).kind == "deadpan_logic"


async def test_first_and_followup_delays_use_injected_timing_and_one_task() -> None:
    sleeper = ControlledSleep()
    calls: list[tuple[TopicSeed, str, int, int, tuple[str, ...]]] = []

    async def process(*args):
        calls.append(args)
        return "鲨鱼生活在海里，因为陆地很难游泳。"

    runtime = ProactiveTopicRuntime(
        ProactiveTopicsConfig(enabled=True),
        process,
        lambda task_id: asyncio.sleep(0),
        sleep=sleeper,
        interval_picker=lambda minimum, maximum: (minimum + maximum) / 2,
        id_factory=lambda: "task-1",
    )
    try:
        await runtime.update_status(_live_status())
        await runtime.update_status(_live_status())
        await _settle()
        assert sleeper.delays == [60]

        await sleeper.release()
        assert len(calls) == 1
        assert calls[0][2:4] == (42, 7)
        assert sleeper.delays == [60, 135]
        assert runtime.recent_outputs == ("鲨鱼生活在海里，因为陆地很难游泳",)
    finally:
        await runtime.close()


async def test_viewer_activity_cancels_generation_and_stops_owned_audio() -> None:
    sleeper = ControlledSleep()
    started = asyncio.Event()
    interrupted: list[str] = []

    async def process(*_args):
        started.set()
        await asyncio.Future()
        return "unreachable"

    async def interrupt(task_id: str) -> None:
        interrupted.append(task_id)

    runtime = ProactiveTopicRuntime(
        ProactiveTopicsConfig(enabled=True),
        process,
        interrupt,
        sleep=sleeper,
        id_factory=lambda: "owned-task",
    )
    try:
        await runtime.update_status(_live_status())
        await sleeper.release()
        await started.wait()

        await runtime.notify_activity()
        await _settle()

        assert interrupted == ["owned-task"]
        assert runtime.metrics.cancelled == 1
        assert runtime.metrics.activity_resets == 1
        assert sleeper.delays == [60, 60]
    finally:
        await runtime.close()


async def test_busy_queue_delays_attempt_and_non_live_states_cancel() -> None:
    sleeper = ControlledSleep()
    busy = True
    calls = 0

    async def process(*_args):
        nonlocal calls
        calls += 1
        return "如果忘记密码，可以试试回忆一下。"

    runtime = ProactiveTopicRuntime(
        ProactiveTopicsConfig(enabled=True),
        process,
        lambda task_id: asyncio.sleep(0),
        sleep=sleeper,
        busy=lambda: busy,
    )
    try:
        await runtime.update_status(_live_status())
        await sleeper.release()
        assert calls == 0
        assert runtime.metrics.skipped_busy == 1
        assert sleeper.delays == [60, 60]

        await runtime.update_status({"state": "reconnecting", "room_id": 42, "generation_id": 7})
        await _settle()
        assert len(sleeper.delays) == 2

        busy = False
        await runtime.update_status(_live_status(generation_id=8))
        await _settle()
        assert sleeper.delays == [60, 60, 60]
    finally:
        await runtime.close()


async def test_source_protocol_accepts_future_approved_meme_adapter() -> None:
    class ApprovedMemeSource:
        async def next_seed(self, context: TopicContext) -> TopicSeed | None:
            del context
            return TopicSeed(
                kind="approved_meme",
                subject="已审核候选",
                dedupe_key="meme:approved-1",
                provenance="approved_catalog",
            )

    sleeper = ControlledSleep()
    selected: list[TopicSeed] = []

    async def process(seed, *_args):
        selected.append(seed)
        return "企鹅不会飞，因为没有买机票。"

    runtime = ProactiveTopicRuntime(
        ProactiveTopicsConfig(enabled=True),
        process,
        lambda task_id: asyncio.sleep(0),
        sources=(ApprovedMemeSource(),),
        sleep=sleeper,
    )
    try:
        await runtime.update_status(_live_status())
        await sleeper.release()
        assert selected[0].kind == "approved_meme"
    finally:
        await runtime.close()
