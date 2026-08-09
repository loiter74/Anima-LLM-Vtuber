"""Viewer attachment is delegated to mc-mcp."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge
from animetta.tools.minecraft.core.config import MinecraftConfig


@pytest.mark.asyncio
async def test_anima_requests_reattach_without_username_or_retry_policy() -> None:
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._ensure_client = AsyncMock()
    bridge.call_tool = AsyncMock(return_value={"viewer": {"confirmed": True}})

    await bridge.reattach_viewer(request_id="manual-reattach")

    bridge.call_tool.assert_awaited_once_with(
        "minecraft_reattach_viewer", {"request_id": "manual-reattach"}
    )
