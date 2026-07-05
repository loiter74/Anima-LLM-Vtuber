"""Tests for gamebot tool adapter — generic command-backed tool helper."""

from __future__ import annotations

from typing import Any

import pytest

from animetta.tools.gamebot.tools import create_tool_helper


class FakeClient:
    """Fake GameBotClient that returns controllable command responses."""

    def __init__(self) -> None:
        self._response: dict[str, Any] = {"status": "success", "result": "ok"}
        self.last_action: str | None = None
        self.last_params: dict[str, Any] | None = None
        self.last_timeout: float | None = None

    async def send_command(self, action: str, params: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        self.last_action = action
        self.last_params = params
        self.last_timeout = timeout
        return self._response

    def set_response(self, resp: dict[str, Any]) -> None:
        self._response = resp


@pytest.mark.asyncio
async def test_tool_helper_calls_send_command() -> None:
    """The helper must call the provided send_command with action, params, and timeout."""
    client = FakeClient()

    helper = create_tool_helper(client.send_command)
    result = await helper("mine", {"block_type": "stone", "count": 3}, timeout=30.0)

    assert client.last_action == "mine"
    assert client.last_params == {"block_type": "stone", "count": 3}
    assert client.last_timeout == 30.0
    assert result == "ok"


@pytest.mark.asyncio
async def test_tool_helper_error_response() -> None:
    """Error responses must become user-readable tool output."""
    client = FakeClient()
    client.set_response({"status": "error", "result": "bot is dead"})

    helper = create_tool_helper(client.send_command)
    result = await helper("goto", {}, timeout=5.0)

    assert "Action failed" in result
    assert "bot is dead" in result


@pytest.mark.asyncio
async def test_tool_helper_dict_result_formatted() -> None:
    """Dict results must be formatted into readable text."""
    client = FakeClient()
    client.set_response({"status": "success", "result": {"health": 20, "food": 16}})

    helper = create_tool_helper(client.send_command)
    result = await helper("status", {}, timeout=5.0)

    assert "health: 20" in result
    assert "food: 16" in result


def test_tool_helper_no_imports_minecraft() -> None:
    """The gamebot/tools.py module must not import any Minecraft-specific module."""
    import inspect

    from animetta.tools.gamebot import tools as tools_mod

    source = inspect.getsource(tools_mod)
    # Only check import statements, not docstrings
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("from", "import")) and not stripped.startswith("#"):
            assert "minecraft" not in stripped, (
                f"gamebot/tools.py imports Minecraft code: {stripped}"
            )
