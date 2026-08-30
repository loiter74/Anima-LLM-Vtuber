from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.orchestration.server.handlers import minecraft_handlers
from animetta.orchestration.server.handlers.minecraft_handlers import (
    TRUSTED_MINECRAFT_ROOM,
    MinecraftHandlers,
)


@pytest.mark.asyncio
async def test_public_activity_goes_only_through_director() -> None:
    sio = AsyncMock()
    director = AsyncMock()
    handler = MinecraftHandlers(sio, director)
    payload = {
        "event": "minecraft.activity.projection",
        "event_id": "activity:1",
    }

    await handler._emit_transition(payload)

    director.submit.assert_awaited_once_with(payload)
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_profile_mode_reconfigures_director_without_public_emit() -> None:
    sio = AsyncMock()
    director = MagicMock()
    handler = MinecraftHandlers(sio, director)

    await handler._emit_transition(
        {
            "event": "minecraft.presentation.configured",
            "mode": "off",
            "profile": "external-review",
            "replay_limit": 7,
        }
    )

    director.configure.assert_called_once_with("off", replay_limit=7)
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_projection_is_emitted_only_to_trusted_room() -> None:
    sio = AsyncMock()
    handler = MinecraftHandlers(sio)
    payload = {
        "event": "minecraft.mission.projection",
        "event_id": "mission:1",
    }

    await handler._emit_transition(payload)

    sio.emit.assert_awaited_once()
    assert sio.emit.await_args.kwargs["to"] == TRUSTED_MINECRAFT_ROOM


@pytest.mark.asyncio
async def test_public_connect_replays_durable_activity_without_client_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = MagicMock()
    projection.model_dump.return_value = {"event_id": "activity:9"}
    read_replay = AsyncMock(return_value=SimpleNamespace(events=(projection,)))
    monkeypatch.setattr(
        minecraft_handlers.mc_tools,
        "read_minecraft_public_activity_replay",
        read_replay,
    )
    director = AsyncMock()
    director.replay_limit = 7
    handler = MinecraftHandlers(AsyncMock(), director)

    await handler.replay_public("public-sid")

    read_replay.assert_awaited_once_with(limit=7)
    director.replay_persisted.assert_awaited_once_with(
        [{"event_id": "activity:9"}],
        "public-sid",
    )
