"""T13: mc_voyager_learn / mc_voyager_live entry tools (mc-bot-voyager-learning)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from animetta.tools.minecraft.core import tools


def _running_bridge(*, autonomous_loop=None) -> AsyncMock:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command = AsyncMock(
        return_value={
            "status": "success",
            "result": "Voyager LEARN mode enabled in external runtime.",
        }
    )
    bridge._autonomous_loop = autonomous_loop
    return bridge


async def test_learn_switches_mode():
    bridge = _running_bridge()
    tools._bridge = bridge
    try:
        out = await tools.mc_voyager_learn.ainvoke({})
    finally:
        tools._bridge = None

    assert "LEARN" in out
    bridge.send_command.assert_awaited_with(
        "set_voyager_mode", {"mode": "learn"}, timeout=10.0
    )
    tools._bridge = None


async def test_live_no_goal_switches_mode():
    bridge = _running_bridge()
    bridge.send_command = AsyncMock(
        return_value={
            "status": "success",
            "result": "Voyager LIVE mode enabled in external runtime.",
        }
    )
    tools._bridge = bridge
    try:
        out = await tools.mc_voyager_live.ainvoke({})
    finally:
        tools._bridge = None

    assert "LIVE" in out
    bridge.send_command.assert_awaited_with(
        "set_voyager_mode", {"mode": "live"}, timeout=10.0
    )


async def test_live_with_goal_but_no_library_defers():
    bridge = _running_bridge(autonomous_loop=None)  # 无 loop → 无 library
    bridge.send_command = AsyncMock(
        side_effect=[
            {"status": "success", "result": "Voyager LIVE mode enabled in external runtime."},
            {
                "status": "error",
                "result": {
                    "code": "EXTERNAL_VOYAGER_GOAL_NOT_IMPLEMENTED",
                    "message": "External runtime has accepted Voyager LIVE mode, but goal execution is not implemented yet.",
                    "goal": "collect wood",
                },
            },
        ]
    )
    tools._bridge = bridge
    try:
        out = await tools.mc_voyager_live.ainvoke({"goal": "collect wood"})
    finally:
        tools._bridge = None

    assert bridge.send_command.await_args_list[0].args == ("set_voyager_mode", {"mode": "live"})
    assert bridge.send_command.await_args_list[1].args == (
        "voyager_live_goal",
        {"goal": "collect wood"},
    )
    assert "not implemented" in out.lower()


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
