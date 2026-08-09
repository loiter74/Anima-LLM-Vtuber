"""Viewer ownership stays behind the mc-mcp boundary."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from animetta.tools.minecraft.core.bridge import MinecraftMcpBridge
from animetta.tools.minecraft.core.config import MinecraftConfig


@pytest.mark.asyncio
async def test_reattach_only_calls_mc_side_controller() -> None:
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._ensure_client = AsyncMock()
    bridge.call_tool = AsyncMock(return_value={"viewer": {"state": "attached"}})

    result = await bridge.reattach_viewer(request_id="viewer-1")

    assert result["viewer"]["state"] == "attached"
    bridge.call_tool.assert_awaited_once_with(
        "minecraft_reattach_viewer", {"request_id": "viewer-1"}
    )
