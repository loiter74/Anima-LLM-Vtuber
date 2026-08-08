from __future__ import annotations

"""Tests for LangChain tool adapter creation."""

import builtins
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from animetta.tools.langchain_tools import (
    get_available_langchain_tools,
    get_python_repl_tool,
    load_langchain_tools,
)


class TestGetAvailableLangChainTools:
    """get_available_langchain_tools function tests."""

    def test_available_tools_contains_only_registered_tools(self):
        assert get_available_langchain_tools() == ["python_repl"]


class TestLoadLangChainTools:
    """load_langchain_tools function tests."""

    @pytest.mark.parametrize("enabled_tools", [None, []])
    def test_load_without_enabled_tools_returns_empty(self, enabled_tools):
        assert load_langchain_tools(enabled_tools=enabled_tools) == []

    def test_load_unknown_tool_returns_empty(self):
        tools = load_langchain_tools(enabled_tools=["nonexistent_tool"])
        assert tools == []

    def test_load_python_repl_mocked(self):
        mock_tool = MagicMock()
        mock_tool.name = "python_repl"

        # Patch the getter dict directly since _LANGCHAIN_TOOL_GETTERS holds a reference
        with patch.dict(
            "animetta.tools.langchain_tools._LANGCHAIN_TOOL_GETTERS",
            {"python_repl": lambda: mock_tool},
        ):
            tools = load_langchain_tools(enabled_tools=["python_repl"])
            assert len(tools) == 1
            assert tools[0].name == "python_repl"

    def test_load_python_repl_not_available(self):
        with patch.dict(
            "animetta.tools.langchain_tools._LANGCHAIN_TOOL_GETTERS",
            {"python_repl": lambda: None},
        ):
            tools = load_langchain_tools(enabled_tools=["python_repl"])
        assert tools == []


class TestGetPythonReplTool:
    """get_python_repl_tool function tests."""

    def test_python_repl_import_error_path(self):
        """A missing optional dependency degrades without using host state."""
        real_import = builtins.__import__

        def reject_experimental(name, *args, **kwargs):
            if name.startswith("langchain_experimental"):
                raise ImportError("optional dependency unavailable")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=reject_experimental):
            assert get_python_repl_tool() is None

    async def test_python_repl_creation_success_and_error_paths(self):
        """One isolated adapter test covers creation and both execution outcomes."""
        mock_repl = MagicMock()
        mock_repl.run.return_value = "calculation result: 42"
        package = ModuleType("langchain_experimental")
        package.__path__ = []
        utilities = ModuleType("langchain_experimental.utilities")
        utilities.PythonREPL = MagicMock(return_value=mock_repl)

        with patch.dict(
            sys.modules,
            {
                "langchain_experimental": package,
                "langchain_experimental.utilities": utilities,
            },
        ):
            tool = get_python_repl_tool()
            assert tool is not None
            assert tool.name == "python_repl"
            assert "Python code" in tool.description

            result = await tool.coroutine("2 + 2")
            assert "calculation result: 42" in result

            mock_repl.run.side_effect = ValueError("syntax error")
            result = await tool.coroutine("invalid code{{{")
            assert "error" in result.lower()
