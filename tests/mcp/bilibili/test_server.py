"""In-memory MCP protocol tests for the Bilibili tool surface."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from mcp.shared.memory import create_connected_server_and_client_session

from tooling.bilibili_mcp.controller import BilibiliController
from tooling.bilibili_mcp.server import create_server

from .test_controller import FakeSocketIOClient, status


async def test_mcp_discovers_six_chinese_documented_tools() -> None:
    controller = BilibiliController(
        client=FakeSocketIOClient(status("stopped", 0)),
    )
    server = create_server(controller)

    async with create_connected_server_and_client_session(
        server,
        read_timeout_seconds=timedelta(seconds=2),
    ) as session:
        tools = (await session.list_tools()).tools

    assert {tool.name for tool in tools} == {
        "bilibili_get_status",
        "bilibili_connect",
        "bilibili_switch_room",
        "bilibili_disconnect",
        "bilibili_wait_for_state",
        "bilibili_get_recent_events",
    }
    assert all(
        tool.description and any("\u4e00" <= char <= "\u9fff" for char in tool.description)
        for tool in tools
    )


async def test_mcp_status_call_returns_structured_content_without_stdout(
    capsys: Any,
) -> None:
    controller = BilibiliController(
        client=FakeSocketIOClient(status("stopped", 0)),
    )
    server = create_server(controller)

    async with create_connected_server_and_client_session(
        server,
        read_timeout_seconds=timedelta(seconds=2),
    ) as session:
        result = await session.call_tool("bilibili_get_status", {})

    captured = capsys.readouterr()
    assert captured.out == ""
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["ok"] is True
    assert result.structuredContent["status"]["state"] == "stopped"
    assert "SESSDATA" not in repr(result)
