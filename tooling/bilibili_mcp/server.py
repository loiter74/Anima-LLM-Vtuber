"""FastMCP tool surface for the Animetta Bilibili controller."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from .controller import BilibiliController


def create_server(controller: BilibiliController | None = None) -> FastMCP[None]:
    """Create an injectable, development-only Bilibili MCP server."""
    active_controller = controller or BilibiliController(
        os.environ.get("ANIMETTA_MCP_URL", "http://127.0.0.1")
    )

    @asynccontextmanager
    async def lifespan(_server: FastMCP[None]) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            await active_controller.close()

    server: FastMCP[None] = FastMCP(
        "animetta-bilibili",
        instructions=(
            "控制本机 Animetta 后端持有的唯一 Bilibili 直播会话。"
            "本服务不会启动 Animetta，也不会直接连接 Bilibili。"
        ),
        log_level="ERROR",
        lifespan=lifespan,
    )

    @server.tool(name="bilibili_get_status")
    async def bilibili_get_status() -> dict[str, Any]:
        """返回后端发布的权威 Bilibili 直播会话快照。"""
        return await active_controller.get_status()

    @server.tool(name="bilibili_connect")
    async def bilibili_connect(
        room_id: int,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """从停止或错误状态连接房间，并等待进入直播或错误状态。"""
        return await active_controller.connect_room(room_id, timeout_seconds)

    @server.tool(name="bilibili_switch_room")
    async def bilibili_switch_room(
        room_id: int,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """使用 generation 乐观并发检查，原子切换到另一个直播房间。"""
        return await active_controller.switch_room(room_id, timeout_seconds)

    @server.tool(name="bilibili_disconnect")
    async def bilibili_disconnect(timeout_seconds: float = 10.0) -> dict[str, Any]:
        """停止后端持有的 Bilibili 直播会话。"""
        return await active_controller.disconnect_room(timeout_seconds)

    @server.tool(name="bilibili_wait_for_state")
    async def bilibili_wait_for_state(
        target_state: str,
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        """通过后端推送通知等待指定的 Bilibili 直播状态。"""
        return await active_controller.wait_for_state(target_state, timeout_seconds)

    @server.tool(name="bilibili_get_recent_events")
    async def bilibili_get_recent_events(
        limit: int = 50,
        event_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """返回当前 generation 最近的完整规范化直播事件。"""
        return await active_controller.get_recent_events(limit, event_types)

    return server


def main() -> None:
    """Run the MCP server with stdout reserved for stdio protocol frames."""
    create_server().run(transport="stdio")
