from __future__ import annotations

import threading

import pytest

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from animetta.services.bilibili.replay_gateway import (
    HIGH_HEAT_BURSTS,
    ReplayDanmakuGateway,
    ReplayTimeline,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.waits: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        self.now += timeout
        return False


def make_events() -> list[LivestreamEvent]:
    return [
        LivestreamEvent(0, 0, LivestreamEventType.ENTER, "viewer_0001"),
        LivestreamEvent(1, 1_000, LivestreamEventType.DANMAKU, "viewer_0001", "one"),
        LivestreamEvent(2, 2_000, LivestreamEventType.DANMAKU, "viewer_0002", "two"),
    ]


def test_replay_preserves_sequence_and_applies_base_speed() -> None:
    clock = FakeClock()
    received: list[int] = []
    gateway = ReplayDanmakuGateway(
        make_events(),
        speed=10,
        monotonic=clock.monotonic,
        waiter=clock.wait,
    )
    gateway.set_event_callback(lambda event: received.append(event.sequence))

    gateway.start()
    assert gateway.wait_until_complete(1.0)

    assert received == [0, 1, 2]
    assert sum(clock.waits) == pytest.approx(0.2)
    assert gateway.metrics.dispatched == 3
    assert gateway.metrics.scheduling_lag_p95_ms == 0
    assert gateway.metrics.scheduling_lag_max_ms == 0


def test_high_heat_bursts_use_continuous_replay_timeline() -> None:
    timeline = ReplayTimeline(speed=1, burst_windows=HIGH_HEAT_BURSTS)

    assert timeline.target_elapsed_seconds(1_800_000) == 1_800
    assert timeline.target_elapsed_seconds(1_920_000) == 1_860
    assert timeline.target_elapsed_seconds(3_660_000) == 3_600
    assert timeline.target_elapsed_seconds(3_750_000) == 3_630
    assert timeline.target_elapsed_seconds(4_920_000) == 4_800
    assert timeline.target_elapsed_seconds(5_160_000) == 4_920


def test_replay_metrics_report_unfinished_configured_burst_windows() -> None:
    clock = FakeClock()
    gateway = ReplayDanmakuGateway(
        [LivestreamEvent(0, 3_750_000, LivestreamEventType.DANMAKU, "viewer", "测试")],
        burst_windows=HIGH_HEAT_BURSTS,
        monotonic=clock.monotonic,
        waiter=clock.wait,
    )

    gateway.start()
    assert gateway.wait_until_complete(1.0)

    burst_profile = gateway.metrics.to_dict()["burst_profile"]
    assert burst_profile["configured"] == 3
    assert burst_profile["completed"] == 2
    assert burst_profile["all_completed"] is False
    assert [window["completed"] for window in burst_profile["windows"]] == [
        True,
        True,
        False,
    ]


def test_legacy_message_callback_receives_only_replyable_events() -> None:
    clock = FakeClock()
    messages = []
    gateway = ReplayDanmakuGateway(
        make_events(),
        speed=10,
        monotonic=clock.monotonic,
        waiter=clock.wait,
    )
    gateway.set_message_callback(messages.append)

    gateway.start()
    assert gateway.wait_until_complete(1.0)

    assert [message.text for message in messages] == ["one", "two"]


def test_stop_from_callback_prevents_later_events_and_is_idempotent() -> None:
    clock = FakeClock()
    received: list[int] = []
    gateway: ReplayDanmakuGateway

    def stop_after_first(event: LivestreamEvent) -> None:
        received.append(event.sequence)
        gateway.stop()

    gateway = ReplayDanmakuGateway(
        make_events(),
        monotonic=clock.monotonic,
        waiter=clock.wait,
    )
    gateway.set_event_callback(stop_after_first)

    gateway.start()
    assert gateway.wait_until_complete(1.0)
    gateway.stop()

    assert received == [0]
    assert gateway.is_running is False
    assert gateway.thread_alive is False
    assert gateway.pending_callback_count == 0


def test_callback_failure_is_accounted_without_killing_replay() -> None:
    clock = FakeClock()
    called = threading.Event()
    gateway = ReplayDanmakuGateway(
        make_events(),
        speed=10,
        monotonic=clock.monotonic,
        waiter=clock.wait,
    )

    def broken(_event: LivestreamEvent) -> None:
        called.set()
        raise RuntimeError("boom")

    gateway.set_event_callback(broken)
    gateway.start()

    assert gateway.wait_until_complete(1.0)
    assert called.is_set()
    assert gateway.metrics.callback_failures == 3
    assert gateway.metrics.dispatched == 0
