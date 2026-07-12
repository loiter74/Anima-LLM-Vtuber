"""Socket.IO lifecycle wiring for the single Python Voyager controller."""

from unittest.mock import AsyncMock

from animetta.core.service_pool import ServicePool
from animetta.orchestration.server.handlers.minecraft_handlers import MinecraftHandlers
from animetta.tools.minecraft.core import tools as mc_tools


async def test_handler_configures_voyager_from_shared_llm(monkeypatch) -> None:
    llm = object()
    bridge = object()
    configure = AsyncMock()
    monkeypatch.setattr(ServicePool, "_ready", True)
    monkeypatch.setattr(ServicePool, "_llm", llm)
    monkeypatch.setattr(mc_tools, "configure_voyager_controller", configure)

    handler = MinecraftHandlers(AsyncMock())
    configured = await handler._configure_voyager(bridge)

    assert configured is True
    configure.assert_awaited_once_with(bridge, llm_service=llm)


async def test_handler_keeps_regular_bridge_available_without_llm(monkeypatch) -> None:
    configure = AsyncMock()
    monkeypatch.setattr(ServicePool, "_ready", False)
    monkeypatch.setattr(ServicePool, "_llm", None)
    monkeypatch.setattr(mc_tools, "configure_voyager_controller", configure)

    handler = MinecraftHandlers(AsyncMock())
    configured = await handler._configure_voyager(object())

    assert configured is False
    configure.assert_not_awaited()
