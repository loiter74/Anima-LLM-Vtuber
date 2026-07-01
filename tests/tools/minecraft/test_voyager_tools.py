"""T13: mc_voyager_learn / mc_voyager_live entry tools (mc-bot-voyager-learning)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from animetta.tools.minecraft.core import tools


def _running_bridge(*, autonomous_loop=None) -> AsyncMock:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.set_voyager_mode = AsyncMock(return_value={"status": "ok", "voyager_mode": "learn"})
    bridge._autonomous_loop = autonomous_loop
    return bridge


async def test_learn_switches_mode():
    tools._bridge = _running_bridge()
    try:
        out = await tools.mc_voyager_learn.ainvoke({})
    finally:
        tools._bridge = None

    assert "LEARN" in out
    tools._bridge = None


async def test_live_no_goal_switches_mode():
    bridge = _running_bridge()
    tools._bridge = bridge
    try:
        out = await tools.mc_voyager_live.ainvoke({})
    finally:
        tools._bridge = None

    assert "LIVE" in out
    bridge.set_voyager_mode.assert_awaited_with("live")


async def test_live_with_goal_but_no_library_defers():
    bridge = _running_bridge(autonomous_loop=None)  # 无 loop → 无 library
    tools._bridge = bridge
    try:
        out = await tools.mc_voyager_live.ainvoke({"goal": "collect wood"})
    finally:
        tools._bridge = None

    bridge.set_voyager_mode.assert_awaited_with("live")
    assert "deferred" in out.lower()


async def test_not_connected_returns_warning():
    tools._bridge = None
    out = await tools.mc_voyager_learn.ainvoke({})
    assert "not connected" in out.lower()

    out = await tools.mc_voyager_live.ainvoke({"goal": "x"})
    assert "not connected" in out.lower()


def test_tools_registered():
    """两个 Voyager 入口 tool 已注册到 get_minecraft_tools()。"""
    registered = tools.get_minecraft_tools()
    assert tools.mc_voyager_learn in registered
    assert tools.mc_voyager_live in registered
    # mc_survival_iron 保留为 fallback 入口
    assert tools.mc_survival_iron in registered
