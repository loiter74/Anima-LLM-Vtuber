from __future__ import annotations

"""Tests for built-in tools (calculator, get_current_time, load_tools_from_config)."""

import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from animetta.tools.base import (
    calculator,
    create_tool_registry,
    get_builtin_tools,
    get_current_time,
    get_tools_map,
    load_tools_from_config,
    web_search,
)


class TestCalculator:
    """Calculator tool tests."""

    @pytest.mark.asyncio
    async def test_calculator_addition(self):
        result = await calculator.coroutine("1 + 2")
        assert "Result: 1 + 2 = 3" in result

    @pytest.mark.asyncio
    async def test_calculator_subtraction(self):
        result = await calculator.coroutine("10 - 4")
        assert "Result: 10 - 4 = 6" in result

    @pytest.mark.asyncio
    async def test_calculator_multiplication(self):
        result = await calculator.coroutine("3 * 5")
        assert "Result: 3 * 5 = 15" in result

    @pytest.mark.asyncio
    async def test_calculator_division(self):
        result = await calculator.coroutine("20 / 4")
        assert "Result: 20 / 4 = 5.0" in result

    @pytest.mark.asyncio
    async def test_calculator_power(self):
        result = await calculator.coroutine("2 ** 10")
        assert "Result: 2 ** 10 = 1024" in result

    @pytest.mark.asyncio
    async def test_calculator_invalid_expression(self):
        result = await calculator.coroutine("not a math expr")
        assert "Calculation failed" in result

    @pytest.mark.asyncio
    async def test_calculator_negative(self):
        result = await calculator.coroutine("-5 + 3")
        assert "Result: -5 + 3 = -2" in result


class TestGetCurrentTime:
    """get_current_time tool tests."""

    @pytest.mark.asyncio
    async def test_get_current_time_default(self):
        result = await get_current_time.coroutine()
        assert "Current time" in result
        assert "Asia/Shanghai" in result or "local time" in result

    @pytest.mark.asyncio
    async def test_get_current_time_utc(self):
        result = await get_current_time.coroutine(timezone="UTC")
        assert "Current time" in result
        assert "UTC" in result

    @pytest.mark.asyncio
    async def test_get_current_time_invalid_timezone(self):
        result = await get_current_time.coroutine(timezone="Invalid/Zone")
        # Should fall back to local time on error
        assert "Current local time" in result or "Current time" in result

    @pytest.mark.asyncio
    async def test_get_current_time_tokyo(self):
        result = await get_current_time.coroutine(timezone="Asia/Tokyo")
        assert "Current time" in result
        assert "Asia/Tokyo" in result


class TestWebSearch:
    """web_search fallback tests."""

    @pytest.mark.asyncio
    async def test_uses_duckduckgo_fallback_when_tavily_is_unset(self, monkeypatch):
        """web_search uses langchain_community.tools DuckDuckGo fallback."""

        class FakeDuckDuckGoSearchRun:
            def run(self, query: str) -> str:
                return f"fake results for {query}"

        fake_tools_module = ModuleType("langchain_community.tools")
        fake_tools_module.DuckDuckGoSearchRun = FakeDuckDuckGoSearchRun
        monkeypatch.setitem(sys.modules, "langchain_community.tools", fake_tools_module)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        result = await web_search.coroutine("animetta architecture")

        assert "Search results (DuckDuckGo)" in result
        assert "fake results for animetta architecture" in result


class TestLoadToolsFromConfig:
    """load_tools_from_config tests."""

    @pytest.mark.asyncio
    async def test_load_all_builtin_tools(self):
        """Loading without filter should return all 4 built-in tools."""
        tools, tools_map = load_tools_from_config({"builtin_tools": None})
        assert len(tools) >= 4
        assert "web_search" in tools_map
        assert "get_weather" in tools_map
        assert "get_current_time" in tools_map
        assert "calculator" in tools_map

    @pytest.mark.asyncio
    async def test_load_filtered_builtin_tools(self):
        """Loading with a filter list should only return matching tools."""
        tools, tools_map = load_tools_from_config(
            {"builtin_tools": ["calculator", "get_current_time"]}
        )
        assert len(tools) == 2
        assert "calculator" in tools_map
        assert "get_current_time" in tools_map
        assert "web_search" not in tools_map

    @pytest.mark.asyncio
    async def test_load_with_empty_builtin_filter(self):
        """Empty filter list should return no built-in tools."""
        tools, tools_map = load_tools_from_config({"builtin_tools": []})
        assert len(tools) == 0
        assert tools_map == {}

    def test_unavailable_minecraft_runtime_is_not_exposed_to_the_model(self, monkeypatch):
        monkeypatch.delenv("MC_MCP_AUTH_TOKEN", raising=False)
        with patch("animetta.tools.base.shutil.which", return_value=None):
            _tools, tools_map = load_tools_from_config(
                {
                    "builtin_tools": ["calculator"],
                    "minecraft": {
                        "enabled": True,
                        "mcp": {
                            "auth_token_env": "MC_MCP_AUTH_TOKEN",
                            "cli_command": "mc-mcp",
                        },
                    },
                }
            )

        assert set(tools_map) == {"calculator"}
        assert "mc_connection" not in tools_map
        assert "mc_operate_bot" not in tools_map

    def test_configured_minecraft_token_makes_runtime_available(self, monkeypatch):
        from animetta.tools.base import _minecraft_runtime_available

        monkeypatch.setenv("ANIMETTA_TEST_MC_TOKEN", "configured")

        assert _minecraft_runtime_available(
            {
                "mcp": {
                    "auth_token_env": "ANIMETTA_TEST_MC_TOKEN",
                    "cli_command": "missing-mc-mcp",
                }
            }
        )

    @patch("animetta.tools.base.load_tools_from_config")
    def test_get_builtin_tools(self, mock_load):
        tools = get_builtin_tools()
        assert len(tools) == 4
        names = [t.name for t in tools]
        assert "calculator" in names

    def test_get_tools_map(self):
        tools = get_builtin_tools()
        tools_map = get_tools_map(tools)
        assert "calculator" in tools_map
        assert "web_search" in tools_map

    def test_create_tool_registry_filter(self):
        tools, tools_map = create_tool_registry(builtin_enabled=["calculator"])
        assert len(tools) == 1
        assert tools[0].name == "calculator"

    def test_create_tool_registry_with_extra(self):
        from langchain_core.tools import tool

        @tool
        async def dummy_tool(param: str) -> str:
            """A dummy extra tool."""
            return f"dummy: {param}"

        tools, tools_map = create_tool_registry(
            builtin_enabled=["calculator"],
            extra_tools=[dummy_tool],
        )
        assert len(tools) == 2
        assert "calculator" in tools_map
        assert "dummy_tool" in tools_map
