from __future__ import annotations

import asyncio

import pytest

from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from animetta.services.program_script import ProgramReplayCoordinator, ReplayCoordinatorError


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


async def test_replay_accepts_matching_prelive_room() -> None:
    coordinator = ProgramReplayCoordinator()
    received = asyncio.Event()

    async def dispatch(_event: LivestreamEvent) -> None:
        received.set()

    coordinator.set_dispatcher(dispatch)
    coordinator.set_room_state_provider(
        lambda _room_id: {
            "state": "prelive",
            "room_id": 1914110916,
            "desired_room_id": 1914110916,
        }
    )

    started = await coordinator.start(
        [LivestreamEvent(0, 0, LivestreamEventType.DANMAKU, "viewer", "one")],
        room_id=1914110916,
        creator_id="creator",
        source="jsonl",
        speed=100,
    )

    await asyncio.wait_for(received.wait(), timeout=1)
    await wait_until(lambda: coordinator.get_run(started["replay_id"])["state"] == "completed")


@pytest.mark.parametrize(
    "snapshot",
    [
        {"state": "live", "room_id": 1914110916},
        {"state": "prelive", "room_id": 123},
    ],
)
async def test_replay_rejects_live_or_other_connected_room(snapshot: dict[str, object]) -> None:
    coordinator = ProgramReplayCoordinator()
    coordinator.set_dispatcher(lambda _event: asyncio.sleep(0))
    coordinator.set_room_state_provider(lambda _room_id: snapshot)

    with pytest.raises(ReplayCoordinatorError) as captured:
        await coordinator.start(
            [LivestreamEvent(0, 0, LivestreamEventType.DANMAKU, "viewer", "one")],
            room_id=1914110916,
            creator_id="creator",
            source="jsonl",
            speed=100,
        )

    assert captured.value.code == "room_input_active"


async def test_replay_pause_waits_for_the_current_dispatch_within_the_control_bound() -> None:
    coordinator = ProgramReplayCoordinator(control_timeout_seconds=0.2)
    started_dispatch = asyncio.Event()
    release_dispatch = asyncio.Event()

    async def dispatch(_event: LivestreamEvent) -> None:
        started_dispatch.set()
        await release_dispatch.wait()

    coordinator.set_dispatcher(dispatch)
    coordinator.set_room_state_provider(lambda _room_id: {"state": "stopped"})
    started = await coordinator.start(
        [LivestreamEvent(0, 0, LivestreamEventType.DANMAKU, "viewer", "one")],
        room_id=1,
        creator_id="creator",
        source="jsonl",
        speed=1,
    )
    await asyncio.wait_for(started_dispatch.wait(), timeout=1)

    pause_task = asyncio.create_task(
        coordinator.control(started["replay_id"], "pause", creator_id="creator")
    )
    await asyncio.sleep(0.05)
    assert not pause_task.done()
    release_dispatch.set()

    paused = await asyncio.wait_for(pause_task, timeout=1)
    assert paused["state"] == "paused"
    assert paused["cursor"] == 1


async def test_replay_pause_timeout_is_a_domain_error_and_eventually_settles() -> None:
    coordinator = ProgramReplayCoordinator(control_timeout_seconds=0.01)
    started_dispatch = asyncio.Event()
    release_dispatch = asyncio.Event()

    async def dispatch(_event: LivestreamEvent) -> None:
        started_dispatch.set()
        await release_dispatch.wait()

    coordinator.set_dispatcher(dispatch)
    coordinator.set_room_state_provider(lambda _room_id: {"state": "stopped"})
    started = await coordinator.start(
        [LivestreamEvent(0, 0, LivestreamEventType.DANMAKU, "viewer", "one")],
        room_id=1,
        creator_id="creator",
        source="jsonl",
        speed=1,
    )
    await asyncio.wait_for(started_dispatch.wait(), timeout=1)

    with pytest.raises(ReplayCoordinatorError, match="当前事件仍在处理") as captured:
        await coordinator.control(started["replay_id"], "pause", creator_id="creator")
    assert captured.value.code == "replay_control_timeout"
    assert captured.value.status_code == 504

    release_dispatch.set()
    await wait_until(lambda: coordinator.get_run(started["replay_id"])["state"] == "paused")
