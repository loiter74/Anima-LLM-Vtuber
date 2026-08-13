from __future__ import annotations

import pytest

from animetta.services.bilibili.danmaku_service import DanmakuService
from animetta.services.bilibili.models import LivestreamEventType


class FakeRoom:
    def __init__(self, live_status: int) -> None:
        self.live_status = live_status

    async def get_room_play_info(self) -> dict[str, int]:
        return {"live_status": self.live_status}


@pytest.mark.parametrize(
    ("live_status", "is_live"),
    [(0, False), (1, True), (2, False)],
)
async def test_initial_room_status_publishes_authoritative_broadcast_state(
    live_status: int,
    is_live: bool,
) -> None:
    service = DanmakuService(room_id=1914110916)

    await service._sync_initial_broadcast_state(FakeRoom(live_status))

    event = service._queue.get_nowait()
    assert event.event_type is LivestreamEventType.BROADCAST_STATE
    assert event.payload["live"] is is_live


async def test_realtime_broadcast_event_wins_over_stale_initial_query() -> None:
    service = DanmakuService(room_id=1914110916)
    service._broadcast_event_seen = True

    await service._sync_initial_broadcast_state(FakeRoom(0))

    assert service._queue.empty()
