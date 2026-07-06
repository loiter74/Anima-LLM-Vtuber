from __future__ import annotations

"""Tests for LangChain tool adapter creation."""

from unittest.mock import MagicMock, patch

import pytest

from animetta.tools.langchain_tools import (
    get_available_langchain_tools,
    get_python_repl_tool,
    load_langchain_tools,
)


class TestGetAvailableLangChainTools:
    """get_available_langchain_tools function tests."""

    def test_available_tools_contains_python_repl(self):
        tools = get_available_langchain_tools()
        assert "python_repl" in tools

    def test_available_tools_is_list(self):
        tools = get_available_langchain_tools()
        assert isinstance(tools, list)


class TestLoadLangChainTools:
    """load_langchain_tools function tests."""

    def test_load_with_none_enabled_returns_empty(self):
        tools = load_langchain_tools(enabled_tools=None)
        assert tools == []

    def test_load_with_empty_list_returns_empty(self):
        tools = load_langchain_tools(enabled_tools=[])
        assert tools == []

    def test_load_unknown_tool_returns_empty(self):
        tools = load_langchain_tools(enabled_tools=["nonexistent_tool"])
        assert tools == []

    @pytest.mark.skip(reason="Requires Python REPL subprocess")
    def test_load_python_repl_mocked(self):

        mock_tool = MagicMock()
        mock_tool.name = "python_repl"

        # Patch the getter dict directly since _LANGCHAIN_TOOL_GETTERS holds a reference
        with patch.dict("animetta.tools.langchain_tools._LANGCHAIN_TOOL_GETTERS", {"python_repl": lambda: mock_tool}):
            tools = load_langchain_tools(enabled_tools=["python_repl"])
            assert len(tools) == 1
            assert tools[0].name == "python_repl"

    def test_load_python_repl_not_available(self):

        with patch("animetta.tools.langchain_tools.get_python_repl_tool", return_value=None):
            tools = load_langchain_tools(enabled_tools=["python_repl"])
            assert tools == []


class TestGetPythonReplTool:
    """get_python_repl_tool function tests."""

    def test_python_repl_returns_none_when_not_installed(self):
        """When langchain_experimental is not installed, returns None."""

        # The import inside the function should fail since langchain_experimental may not be installed
        tool = get_python_repl_tool()
        if tool is not None:
            pytest.skip("langchain_experimental IS installed, cannot test import error path")
        assert tool is None

    def test_python_repl_import_error_path(self):
        """Test that ImportError is handled gracefully."""

        # Simulate ImportError by patching inside the function boundary
        import animetta.tools.langchain_tools as lt
        orig_getter = lt._LANGCHAIN_TOOL_GETTERS["python_repl"]

        try:
            lt._LANGCHAIN_TOOL_GETTERS["python_repl"] = lambda: None
            tool = get_python_repl_tool()
            assert tool is None
        finally:
            lt._LANGCHAIN_TOOL_GETTERS["python_repl"] = orig_getter

    @pytest.mark.skip(reason="Requires langchain_experimental package (not installed in CI)")
    def test_python_repl_successfully_created(self):

        mock_repl = MagicMock()
        mock_repl.run.return_value = "42"

        with patch("langchain_experimental.utilities.PythonREPL", return_value=mock_repl):
            tool = get_python_repl_tool()
            assert tool is not None
            assert tool.name == "python_repl"
            assert "Python code" in tool.description

    @pytest.mark.skip(reason="Requires langchain_experimental package (not installed in CI)")
    @pytest.mark.asyncio
    async def test_python_repl_execution(self):

        mock_repl = MagicMock()
        mock_repl.run.return_value = "calculation result: 42"

        with patch("langchain_experimental.utilities.PythonREPL", return_value=mock_repl):
            tool = get_python_repl_tool()
            result = await tool.coroutine("2 + 2")
            assert "calculation result: 42" in result

    @pytest.mark.skip(reason="Requires langchain_experimental package (not installed in CI)")
    @pytest.mark.asyncio
    async def test_python_repl_execution_error(self):

        mock_repl = MagicMock()
        mock_repl.run.side_effect = Exception("syntax error")

        with patch("langchain_experimental.utilities.PythonREPL", return_value=mock_repl):
            tool = get_python_repl_tool()
            result = await tool.coroutine("invalid code{{{")
            assert "error" in result.lower()
