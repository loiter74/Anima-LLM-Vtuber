"""Socket.IO lifecycle wiring for the single Python Voyager controller."""

from unittest.mock import ANY, AsyncMock

from animetta.orchestration.server.handlers.minecraft_handlers import MinecraftHandlers
from animetta.orchestration.socket_events import EVENTS
from animetta.tools.minecraft.core import tools as mc_tools


async def test_handler_requires_gamebot_v2_control_plane(monkeypatch) -> None:
    bridge = object()
    configure = AsyncMock()
    monkeypatch.setattr(mc_tools, "configure_voyager_control_plane", configure)

    handler = MinecraftHandlers(AsyncMock())
    configured = await handler._configure_voyager(bridge)

    assert configured is True
    configure.assert_awaited_once_with(bridge, event_emit=ANY)

    event_emit = configure.await_args.kwargs["event_emit"]
    await event_emit({"event_id": "1"})
    handler.sio.emit.assert_awaited_with(
        EVENTS["minecraft"]["command_transition"]["name"], {"event_id": "1"}
    )
    await event_emit({"event": "minecraft.skill.trust", "event_id": "trust:1"})
    handler.sio.emit.assert_awaited_with(
        EVENTS["minecraft"]["skill_trust"]["name"],
        {"event": "minecraft.skill.trust", "event_id": "trust:1"},
    )


def test_minecraft_lifecycle_event_names_are_characterized() -> None:
    assert EVENTS["minecraft"]["start"]["name"] == "minecraft:start"
    assert EVENTS["minecraft"]["stop"]["name"] == "minecraft:stop"
    assert EVENTS["minecraft"]["status"]["name"] == "minecraft:status"
