"""Socket.IO lifecycle wiring for the single Python Voyager controller."""

from unittest.mock import AsyncMock

import pytest

from animetta.orchestration.server.handlers import minecraft_handlers as handlers_module
from animetta.orchestration.server.handlers.minecraft_handlers import MinecraftHandlers
from animetta.orchestration.socket_events import EVENTS


async def test_handler_routes_control_plane_projections() -> None:
    handler = MinecraftHandlers(AsyncMock())
    await handler._emit_transition({"event_id": "1"})
    handler.sio.emit.assert_awaited_with(
        EVENTS["minecraft"]["command_transition"]["name"], {"event_id": "1"}
    )
    await handler._emit_transition({"event": "minecraft.skill.trust", "event_id": "trust:1"})
    handler.sio.emit.assert_awaited_with(
        EVENTS["minecraft"]["skill_trust"]["name"],
        {"event": "minecraft.skill.trust", "event_id": "trust:1"},
    )


def test_minecraft_lifecycle_event_names_are_characterized() -> None:
    assert EVENTS["minecraft"]["connect"]["name"] == "minecraft:connect"
    assert EVENTS["minecraft"]["disconnect"]["name"] == "minecraft:disconnect"
    assert EVENTS["minecraft"]["shutdown"]["name"] == "minecraft:shutdown"
    assert EVENTS["minecraft"]["status"]["name"] == "minecraft:status"


@pytest.mark.asyncio
async def test_reattach_routes_through_public_connection_capability(monkeypatch) -> None:
    manage = AsyncMock(
        return_value={
            "viewer": {
                "binding_state": "following",
                "confirmed": True,
                "username": "Viewer",
            }
        }
    )
    monkeypatch.setattr(handlers_module.mc_tools, "manage_minecraft_connection", manage)
    sio = AsyncMock()
    handler = MinecraftHandlers(sio)

    await handler.on_minecraft_reattach_viewer("sid-1", {"request_id": "reattach-1"})

    manage.assert_awaited_once_with("reattach_viewer", request_id="reattach-1")
    sio.emit.assert_awaited_once_with(
        EVENTS["minecraft"]["viewer_status"]["name"],
        {
            "schema_version": 2,
            "status": "joined",
            "binding_state": "following",
            "confirmed": True,
            "username": "Viewer",
            "mode": "spectator",
            "target": "AnimettaBot",
            "attempt": 0,
            "reason": "unknown",
        },
        to="sid-1",
    )
