from __future__ import annotations

import asyncio
from pathlib import Path

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from animetta.services.bilibili.livestream_session import LivestreamSession
from animetta.services.bilibili.replay_gateway import ReplayDanmakuGateway
from evaluations.livestream.dataset import DatasetValidator, DatasetWriter, HeatTier


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def wait(self, timeout: float) -> bool:
        self.now += timeout
        return False


async def test_validated_jsonl_replays_through_session_and_legacy_sink(tmp_path: Path) -> None:
    writer = DatasetWriter(tmp_path, dataset_id="low-a", heat_tier=HeatTier.LOW)
    writer.write(LivestreamEvent(0, 0, LivestreamEventType.ENTER, "Alice", payload={"user_id": 1}))
    writer.write(
        LivestreamEvent(1, 1_000, LivestreamEventType.DANMAKU, "Alice", "hello", {"user_id": 1}),
    )
    writer.finalize(duration_ms=60_000)
    validation = DatasetValidator().validate(tmp_path)
    assert validation.valid

    clock = FakeClock()
    gateways: list[ReplayDanmakuGateway] = []

    def factory(_room_id: int, _sessdata: str) -> ReplayDanmakuGateway:
        gateway = ReplayDanmakuGateway(
            validation.events,
            speed=10,
            monotonic=clock.monotonic,
            waiter=clock.wait,
        )
        gateways.append(gateway)
        return gateway

    raw_events = []
    raw_messages = []
    session = LivestreamSession(
        gateway_factory=factory,
        raw_event_sink=lambda event, _room_id, _generation_id: _append_async(
            raw_events,
            event,
        ),
        raw_message_sink=lambda message, _room_id: _append_async(raw_messages, message),
    )

    await session.set_room(1)
    assert await asyncio.to_thread(gateways[0].wait_until_complete, 1.0)
    await asyncio.sleep(0.05)

    assert [event.event_type for event in raw_events] == [
        LivestreamEventType.ENTER,
        LivestreamEventType.DANMAKU,
    ]
    assert [message.text for message in raw_messages] == ["hello"]
    assert session.event_metrics.received == 2
    assert session.metrics.received == 1
    await session.stop()


async def _append_async(target: list, value: object) -> None:
    target.append(value)
