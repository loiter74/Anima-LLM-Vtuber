from __future__ import annotations

import asyncio

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from animetta.services.program_script import ProgramReplayCoordinator


async def wait_until(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_replay_pause_step_speed_and_restart() -> None:
    coordinator = ProgramReplayCoordinator()
    received: list[str] = []
    first = asyncio.Event()

    async def dispatch(event: LivestreamEvent) -> None:
        received.append(event.text)
        first.set()

    coordinator.set_dispatcher(dispatch)
    coordinator.set_room_state_provider(lambda _room_id: {"state": "stopped"})
    events = [
        LivestreamEvent(0, 0, LivestreamEventType.DANMAKU, "viewer", "one"),
        LivestreamEvent(1, 60_000, LivestreamEventType.DANMAKU, "viewer", "two"),
    ]
    started = await coordinator.start(
        events,
        room_id=1,
        creator_id="creator",
        source="jsonl",
        speed=1,
    )
    replay_id = started["replay_id"]
    await asyncio.wait_for(first.wait(), timeout=1)
    paused = await coordinator.control(replay_id, "pause", creator_id="creator")

    assert paused["state"] == "paused"
    assert paused["cursor"] == 1

    await coordinator.control(replay_id, "step", creator_id="creator")
    await wait_until(lambda: coordinator.get_run(replay_id)["cursor"] == 2)
    assert received == ["one", "two"]

    restarted = await coordinator.control(
        replay_id,
        "restart",
        creator_id="creator",
        speed=10,
    )
    assert restarted["replay_id"] != replay_id
    assert restarted["speed"] == 10
    await coordinator.control(restarted["replay_id"], "stop", creator_id="creator")


async def test_replay_failure_stops_without_reusing_the_failed_event() -> None:
    coordinator = ProgramReplayCoordinator()

    async def dispatch(_event: LivestreamEvent) -> None:
        raise RuntimeError("delivery failed")

    coordinator.set_dispatcher(dispatch)
    coordinator.set_room_state_provider(lambda _room_id: {"state": "stopped"})
    started = await coordinator.start(
        [LivestreamEvent(0, 0, LivestreamEventType.DANMAKU, "viewer", "one")],
        room_id=1,
        creator_id="creator",
        source="jsonl",
        speed=1,
    )

    await wait_until(lambda: coordinator.get_run(started["replay_id"])["state"] == "failed")
    failed = coordinator.get_run(started["replay_id"])
    assert failed["cursor"] == 0
    assert failed["error"] == "RuntimeError"
