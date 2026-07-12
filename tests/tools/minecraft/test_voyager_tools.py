"""Public Voyager tools route to the single Python control plane."""

from __future__ import annotations

from unittest.mock import AsyncMock

from animetta.tools.minecraft.core import tools
from animetta.tools.minecraft.voyager.contracts import (
    VoyagerMode,
    VoyagerSessionState,
    VoyagerStatus,
)


def _running_bridge() -> AsyncMock:
    bridge = AsyncMock()
    bridge.is_running = True
    bridge.send_command = AsyncMock()
    return bridge


def _controller() -> AsyncMock:
    controller = AsyncMock()
    controller.start_learning.return_value = VoyagerStatus(
        mode=VoyagerMode.LEARN,
        state=VoyagerSessionState.RUNNING,
        session_id="learn-session",
        runtime_id="runtime-1",
    )
    controller.start_live.return_value = VoyagerStatus(
        mode=VoyagerMode.LIVE,
        state=VoyagerSessionState.RUNNING,
        session_id="live-session",
        runtime_id="runtime-1",
    )
    controller.run_live_goal.return_value = {
        "outcome": "success",
        "skill_id": "trusted-wood",
        "evidence_eligible": True,
    }
    return controller


async def test_learn_starts_python_learning_session_without_node_mode_command() -> None:
    bridge = _running_bridge()
    controller = _controller()
    tools._bridge = bridge
    tools._voyager_controller = controller
    try:
        out = await tools.mc_voyager_learn.ainvoke({})
    finally:
        tools._bridge = None
        tools._voyager_controller = None

    controller.start_learning.assert_awaited_once_with()
    bridge.send_command.assert_not_awaited()
    assert "learn-session" in out


async def test_live_without_goal_starts_python_live_session() -> None:
    bridge = _running_bridge()
    controller = _controller()
    tools._bridge = bridge
    tools._voyager_controller = controller
    try:
        out = await tools.mc_voyager_live.ainvoke({})
    finally:
        tools._bridge = None
        tools._voyager_controller = None

    controller.start_live.assert_awaited_once_with()
    controller.run_live_goal.assert_not_awaited()
    bridge.send_command.assert_not_awaited()
    assert "live-session" in out


async def test_live_goal_executes_through_python_live_session() -> None:
    bridge = _running_bridge()
    controller = _controller()
    tools._bridge = bridge
    tools._voyager_controller = controller
    try:
        out = await tools.mc_voyager_live.ainvoke({"goal": "collect wood"})
    finally:
        tools._bridge = None
        tools._voyager_controller = None

    controller.start_live.assert_awaited_once_with()
    controller.run_live_goal.assert_awaited_once_with("collect wood")
    bridge.send_command.assert_not_awaited()
    assert "trusted-wood" in out


async def test_connected_without_controller_returns_configuration_error() -> None:
    tools._bridge = _running_bridge()
    tools._voyager_controller = None
    try:
        out = await tools.mc_voyager_learn.ainvoke({})
    finally:
        tools._bridge = None

    assert "controller" in out.lower()
    assert "not configured" in out.lower()


async def test_not_connected_returns_warning() -> None:
    tools._bridge = None
    tools._voyager_controller = _controller()
    try:
        out = await tools.mc_voyager_learn.ainvoke({})
        assert "not connected" in out.lower()

        out = await tools.mc_voyager_live.ainvoke({"goal": "x"})
        assert "not connected" in out.lower()
    finally:
        tools._voyager_controller = None


def test_tools_registered() -> None:
    registered = tools.get_minecraft_tools()
    assert tools.mc_voyager_learn in registered
    assert tools.mc_voyager_live in registered
    assert tools.mc_survival_iron in registered
