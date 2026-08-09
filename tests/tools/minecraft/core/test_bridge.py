"""Streamable HTTP mc-mcp bridge behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge, MinecraftMcpError
from animetta.tools.minecraft.core.config import MinecraftConfig


def _response(value: dict, *, error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(structuredContent=value, isError=error, content=[])


@pytest.mark.asyncio
async def test_start_uses_profile_and_never_spawns_node_directly(monkeypatch) -> None:
    monkeypatch.setenv("MC_MCP_AUTH_TOKEN", "secret")
    monkeypatch.setenv("MC_MCP_URL", "http://host.docker.internal:18768/mcp")
    client = SimpleNamespace(
        session=object(),
        connect=AsyncMock(return_value=True),
        disconnect=AsyncMock(),
        call_tool=AsyncMock(
            side_effect=[
                _response({"state": "ready", "profile": "external-local"}),
                _response({"events": [], "next_cursor": 0, "overflowed": False}),
            ]
        ),
    )
    with patch(
        "animetta.tools.minecraft.core.bridge.MCPClient", return_value=client
    ) as client_factory:
        bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
        result = await bridge.start(profile="external-local", request_id="connect-1")
        await asyncio.sleep(0)
        await bridge.close()

    assert result["state"] == "ready"
    assert client_factory.call_args.kwargs["url"] == "http://host.docker.internal:18768/mcp"
    assert client.call_tool.await_args_list[0].args == (
        "minecraft_connect",
        {"profile": "external-local", "request_id": "connect-1"},
    )


@pytest.mark.asyncio
async def test_runtime_action_maps_to_mcp_tool() -> None:
    client = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(return_value=_response({"receipt_id": "receipt-1"})),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._client = client

    result = await bridge.send_command("gamebot_v2_execute_action", {"capability": "goto"})

    assert result == {"status": "success", "result": {"receipt_id": "receipt-1"}}
    client.call_tool.assert_awaited_once_with(
        "gamebot_execute_action", {"payload": {"capability": "goto"}}
    )


@pytest.mark.asyncio
async def test_failed_transport_reconnects_once_and_preserves_call(monkeypatch) -> None:
    first = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(return_value=None),
        disconnect=AsyncMock(),
    )
    second = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(return_value=_response({"state": "ready"})),
        disconnect=AsyncMock(),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._client = first
    monkeypatch.setattr(
        bridge,
        "_connect_client",
        AsyncMock(side_effect=lambda: setattr(bridge, "_client", second)),
    )

    result = await bridge.call_tool("minecraft_connection_status", {})

    assert result == {"state": "ready"}
    first.disconnect.assert_awaited_once()
    second.call_tool.assert_awaited_once_with("minecraft_connection_status", {})


@pytest.mark.asyncio
async def test_mcp_error_is_structured_and_not_retried() -> None:
    client = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(
            return_value=_response(
                {"ok": False, "error": {"code": "SERVER_UNAVAILABLE", "message": "offline"}},
                error=True,
            )
        ),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._client = client

    with pytest.raises(MinecraftMcpError, match="SERVER_UNAVAILABLE:offline"):
        await bridge.call_tool("minecraft_connect", {})

    client.call_tool.assert_awaited_once()


def test_viewer_events_are_projected_without_attachment_logic() -> None:
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    callback = Mock()
    bridge.set_viewer_callback(callback)

    bridge._dispatch_event({"type": "client_viewer_status", "confirmed": True})

    callback.assert_called_once_with(
        "client_viewer_status", {"type": "client_viewer_status", "confirmed": True}
    )
