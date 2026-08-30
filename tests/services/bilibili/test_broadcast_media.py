from __future__ import annotations

import asyncio

import pytest

from animetta.services.bilibili.reply_media import (
    BroadcastMediaArbiter,
    BroadcastMediaTurn,
)


@pytest.mark.asyncio
async def test_waiting_media_uses_priority_then_fifo() -> None:
    arbiter = BroadcastMediaArbiter()
    blocker = BroadcastMediaTurn(arbiter, priority=50)
    await blocker.acquire()
    order: list[str] = []

    async def run(name: str, priority: int) -> None:
        turn = BroadcastMediaTurn(arbiter, priority=priority)
        await turn.acquire()
        order.append(name)
        await turn.finish()

    low = asyncio.create_task(run("progress", 50))
    high = asyncio.create_task(run("viewer", 20))
    await asyncio.sleep(0)
    await blocker.finish()
    await asyncio.gather(low, high)

    assert order == ["viewer", "progress"]


@pytest.mark.asyncio
async def test_media_turn_cancel_is_idempotent() -> None:
    turn = BroadcastMediaTurn(BroadcastMediaArbiter(), priority=50)
    await turn.acquire()
    await turn.cancel()
    await turn.cancel()
    assert turn.completed is True


@pytest.mark.asyncio
async def test_media_turn_reports_started_only_after_lease_is_acquired() -> None:
    arbiter = BroadcastMediaArbiter()
    blocker = BroadcastMediaTurn(arbiter, priority=20)
    await blocker.acquire()
    started = asyncio.Event()
    turn = BroadcastMediaTurn(
        arbiter,
        priority=50,
        on_acquired=lambda: _set_event(started),
    )

    acquiring = asyncio.create_task(turn.acquire())
    await asyncio.sleep(0)
    assert not started.is_set()

    await blocker.finish()
    await acquiring
    assert started.is_set()
    await turn.finish()


async def _set_event(event: asyncio.Event) -> None:
    event.set()
