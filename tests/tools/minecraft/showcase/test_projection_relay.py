from __future__ import annotations

import pytest

from animetta.tools.minecraft.showcase.projection_relay import ProjectionSocketRelay


@pytest.mark.asyncio
async def test_projection_relay_broadcasts_and_rehydrates_current_events() -> None:
    emitted: list[tuple[str, dict, str | None]] = []

    class SocketServer:
        async def emit(self, event: str, payload: dict, to: str | None = None) -> None:
            emitted.append((event, payload, to))

    relay = ProjectionSocketRelay(SocketServer())
    first = {
        "event": "minecraft.stage.projection",
        "event_id": "run-1:dialogue:1",
        "projection_kind": "stage",
        "payload": {"run_id": "run-1", "stage_id": "dialogue"},
    }
    second = {
        "event": "minecraft.mission.projection",
        "event_id": "mission-1:1",
        "projection_kind": "mission",
        "payload": {"mission_id": "mission-1"},
    }

    await relay.emit(first)
    await relay.emit(second)
    await relay.replay("viewer-1")

    assert emitted == [
        ("minecraft.stage.projection", first, None),
        ("minecraft.mission.projection", second, None),
        ("minecraft.stage.projection", first, "viewer-1"),
        ("minecraft.mission.projection", second, "viewer-1"),
    ]


@pytest.mark.asyncio
async def test_projection_relay_rejects_non_projection_events() -> None:
    class SocketServer:
        async def emit(self, _event: str, _payload: dict, to: str | None = None) -> None:
            del to

    relay = ProjectionSocketRelay(SocketServer())

    with pytest.raises(ValueError, match="SHOWCASE_PROJECTION_EVENT_INVALID"):
        await relay.emit({"event": "desktop.control", "event_id": "bad"})
