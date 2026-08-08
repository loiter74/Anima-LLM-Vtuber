from __future__ import annotations

from animetta.orchestration.graph.tool_manager import ToolManager
from animetta.tools import MCPManager

"""Tests for ToolManager — tool loading, config, lifecycle."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestToolManager:
    """ToolManager: loads built-in + MCP tools, manages lifecycle."""

    # ── Fixtures ─────────────────────────────────────────────────

    @pytest.fixture
    def tool_manager(self, mock_service_context):
        """Create a ToolManager with mocked service context."""

        return ToolManager(session_id="test_session", service_context=mock_service_context)

    # ── load_tools ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_load_tools_success(self, tool_manager):
        """load_tools loads built-in tools, creates chat model, binds tools."""
        mock_tools = [MagicMock(name="tool1"), MagicMock(name="tool2")]
        mock_tools_map = {"tool1": mock_tools[0], "tool2": mock_tools[1]}
        mock_chat_model = MagicMock()
        mock_chat_model.bind_tools = MagicMock(return_value="bound_model")

        with (
            patch("animetta.orchestration.graph.tool_manager.load_tools_from_config") as mock_load,
            patch.object(
                tool_manager, "_create_chat_model", AsyncMock(return_value=mock_chat_model)
            ),
        ):
            mock_load.return_value = (mock_tools, mock_tools_map)

            result = await tool_manager.load_tools({"builtin": "tools"})

        assert result is True
        assert len(tool_manager.tools) == 2
        assert tool_manager.tools_map == mock_tools_map
        assert tool_manager.chat_model == "bound_model"
        mock_chat_model.bind_tools.assert_called_once_with(mock_tools)

    @pytest.mark.asyncio
    async def test_load_tools_with_mcp_servers(self, tool_manager):
        """When tools_config has mcp_servers, MCP tools are also loaded."""

        mock_tools = [MagicMock(name="builtin_tool")]
        mock_tools_map = {"builtin_tool": mock_tools[0]}
        mock_chat_model = MagicMock()
        mock_chat_model.bind_tools = MagicMock(return_value="bound_model")

        mock_mcp_tool = MagicMock(name="mcp_tool")
        mock_mcp_tool.name = "mcp_tool"

        with (
            patch("animetta.orchestration.graph.tool_manager.load_tools_from_config") as mock_load,
            patch.object(
                tool_manager, "_create_chat_model", AsyncMock(return_value=mock_chat_model)
            ),
            patch("animetta.orchestration.graph.tool_manager.MCPManager") as mock_mcp_cls,
        ):
            mock_load.return_value = (mock_tools, mock_tools_map)
            mock_mcp_instance = MagicMock(spec=MCPManager)
            mock_mcp_instance.load = AsyncMock(return_value=[mock_mcp_tool])
            mock_mcp_cls.return_value = mock_mcp_instance

            result = await tool_manager.load_tools(
                {
                    "builtin": "tools",
                    "mcp_servers": [{"name": "server1"}],
                }
            )

        assert result is True
        assert len(tool_manager.tools) == 2  # builtin + mcp
        assert "mcp_tool" in tool_manager.tools_map
        assert tool_manager._mcp_manager is mock_mcp_instance
        mock_mcp_instance.load.assert_awaited_once_with([{"name": "server1"}])

    @pytest.mark.asyncio
    async def test_load_tools_no_tools_no_bind(self, tool_manager):
        """When no tools are loaded, bind_tools is not called."""
        mock_chat_model = MagicMock()

        with (
            patch("animetta.orchestration.graph.tool_manager.load_tools_from_config") as mock_load,
            patch.object(
                tool_manager, "_create_chat_model", AsyncMock(return_value=mock_chat_model)
            ),
        ):
            mock_load.return_value = ([], {})

            result = await tool_manager.load_tools({"builtin": "tools"})

        assert result is True
        assert len(tool_manager.tools) == 0
        mock_chat_model.bind_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_tools_creation_failure(self, tool_manager):
        """When _create_chat_model fails, load_tools still returns True but chat_model is None."""
        with (
            patch("animetta.orchestration.graph.tool_manager.load_tools_from_config") as mock_load,
            patch.object(tool_manager, "_create_chat_model", AsyncMock(return_value=None)),
        ):
            mock_load.return_value = ([MagicMock(name="t")], {"t": MagicMock()})

            result = await tool_manager.load_tools({"builtin": "tools"})

        assert result is True
        assert tool_manager.chat_model is None

    @pytest.mark.asyncio
    async def test_load_tools_exception_returns_false(self, tool_manager):
        """When load_tools raises, return False."""
        with patch("animetta.orchestration.graph.tool_manager.load_tools_from_config") as mock_load:
            mock_load.side_effect = RuntimeError("oops")

            result = await tool_manager.load_tools({"builtin": "tools"})

        assert result is False

    @pytest.mark.asyncio
    async def test_load_prebuilt_tools_binds_exact_instances_without_config_loader(
        self, tool_manager
    ):
        """A runtime-owned control plane can reuse the ordinary graph without reinitializing it."""

        first = MagicMock()
        first.name = "mc_execute"
        second = MagicMock()
        second.name = "mc_status"
        third = MagicMock()
        third.name = "mc_stop"
        chat_model = MagicMock()
        bound_model = MagicMock()
        chat_model.bind_tools.return_value = bound_model

        assert hasattr(tool_manager, "load_prebuilt_tools")
        with (
            patch("animetta.orchestration.graph.tool_manager.load_tools_from_config") as loader,
            patch.object(
                tool_manager,
                "_create_chat_model",
                AsyncMock(return_value=chat_model),
            ),
        ):
            result = await tool_manager.load_prebuilt_tools([first, second, third])

        assert result is True
        assert tool_manager.tools == [first, second, third]
        assert tool_manager.tools_map == {
            "mc_execute": first,
            "mc_status": second,
            "mc_stop": third,
        }
        assert tool_manager.chat_model is bound_model
        loader.assert_not_called()
        chat_model.bind_tools.assert_called_once_with([first, second, third])

    @pytest.mark.asyncio
    async def test_cleanup_does_not_stop_runtime_owned_by_prebuilt_tools(self, tool_manager):
        tool = MagicMock()
        tool.name = "mc_execute"
        chat_model = MagicMock()
        chat_model.bind_tools.return_value = chat_model
        bridge = MagicMock()
        bridge.is_running = True
        bridge.stop = AsyncMock()

        with (
            patch.object(
                tool_manager,
                "_create_chat_model",
                AsyncMock(return_value=chat_model),
            ),
            patch(
                "animetta.orchestration.graph.tool_manager.get_bridge",
                return_value=bridge,
            ),
        ):
            assert await tool_manager.load_prebuilt_tools([tool]) is True
            await tool_manager.cleanup()

        bridge.stop.assert_not_awaited()

    # ── _create_chat_model ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_create_chat_model_success(self, tool_manager):
        """_create_chat_model wraps the LLM service into a LangChain ChatModel."""
        mock_chat_model = MagicMock()

        with patch(
            "animetta.orchestration.graph.tool_manager.create_chat_model_from_service",
        ) as mock_create:
            mock_create.return_value = mock_chat_model

            result = await tool_manager._create_chat_model()

        assert result is mock_chat_model
        mock_create.assert_called_once_with(
            llm_service=tool_manager.service_context.llm_engine,
            enable_tooling=True,
        )

    @pytest.mark.asyncio
    async def test_create_chat_model_failure_returns_none(self, tool_manager):
        """When create_chat_model_from_service raises, return None."""
        with patch(
            "animetta.orchestration.graph.tool_manager.create_chat_model_from_service",
        ) as mock_create:
            mock_create.side_effect = ImportError("missing dependency")

            result = await tool_manager._create_chat_model()

        assert result is None

    # ── get_config ────────────────────────────────────────────────

    def test_get_config_returns_tools_dict(self, tool_manager):
        """get_config returns the expected tools configuration dict."""
        tool_manager.tools = [MagicMock(name="t1")]
        tool_manager.tools_map = {"t1": MagicMock()}
        tool_manager.chat_model = MagicMock()

        config = tool_manager.get_config()

        assert config["tools"] == tool_manager.tools
        assert config["tools_map"] == tool_manager.tools_map
        assert config["chat_model"] == tool_manager.chat_model
        assert config["enable_tools"] is True

    # ── is_loaded ─────────────────────────────────────────────────

    def test_is_loaded_true_when_tools_and_chat_model(self, tool_manager):
        """is_loaded returns True when tools and chat_model are present."""
        tool_manager.tools = [MagicMock()]
        tool_manager.chat_model = MagicMock()
        assert tool_manager.is_loaded() is True

    def test_is_loaded_false_no_tools(self, tool_manager):
        """is_loaded returns False when no tools are loaded."""
        tool_manager.tools = []
        tool_manager.chat_model = MagicMock()
        assert tool_manager.is_loaded() is False

    def test_is_loaded_false_no_chat_model(self, tool_manager):
        """is_loaded returns False when chat_model is None."""
        tool_manager.tools = [MagicMock()]
        tool_manager.chat_model = None
        assert tool_manager.is_loaded() is False

    def test_is_loaded_false_empty(self, tool_manager):
        """is_loaded returns False when nothing is loaded."""
        assert tool_manager.is_loaded() is False

    # ── cleanup ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_cleanup_with_mcp_manager(self, tool_manager):
        """cleanup closes the MCP manager if present."""
        mock_mcp = MagicMock()
        mock_mcp.close_all = AsyncMock()
        tool_manager._mcp_manager = mock_mcp

        with patch("animetta.orchestration.graph.tool_manager.get_bridge") as mock_get_bridge:
            mock_bridge = MagicMock()
            mock_bridge.is_running = False
            mock_get_bridge.return_value = mock_bridge

            await tool_manager.cleanup()

        mock_mcp.close_all.assert_awaited_once()
        assert tool_manager._mcp_manager is None

    @pytest.mark.asyncio
    async def test_cleanup_without_mcp_manager(self, tool_manager):
        """cleanup works when no MCP manager was created."""
        with patch("animetta.orchestration.graph.tool_manager.get_bridge") as mock_get_bridge:
            mock_bridge = MagicMock()
            mock_bridge.is_running = False
            mock_get_bridge.return_value = mock_bridge

            await tool_manager.cleanup()

        # no crash is the assertion
        assert tool_manager._mcp_manager is None

    @pytest.mark.asyncio
    async def test_cleanup_stops_minecraft_bridge(self, tool_manager):
        """cleanup stops the Minecraft bridge if it is running."""
        with patch("animetta.orchestration.graph.tool_manager.get_bridge") as mock_get_bridge:
            mock_bridge = MagicMock()
            mock_bridge.is_running = True
            mock_bridge.stop = AsyncMock()
            mock_get_bridge.return_value = mock_bridge

            await tool_manager.cleanup()

        mock_bridge.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_handles_minecraft_import_error(self, tool_manager):
        """cleanup handles ImportError when Minecraft tools not installed."""
        with patch("animetta.orchestration.graph.tool_manager.get_bridge") as mock_get_bridge:
            mock_get_bridge.side_effect = ImportError("not installed")

            await tool_manager.cleanup()  # should not raise

        # no exception is the assertion

    @pytest.mark.asyncio
    async def test_cleanup_handles_minecraft_stop_exception(self, tool_manager):
        """cleanup warns but does not crash when Minecraft bridge.stop raises."""
        with patch("animetta.orchestration.graph.tool_manager.get_bridge") as mock_get_bridge:
            mock_bridge = MagicMock()
            mock_bridge.is_running = True
            mock_bridge.stop = AsyncMock(side_effect=RuntimeError("stop failed"))
            mock_get_bridge.return_value = mock_bridge

            await tool_manager.cleanup()  # should not raise

    # ── Constructor ───────────────────────────────────────────────

    def test_constructor_initializes_empty_state(self, mock_service_context):
        """ToolManager starts with empty tools, tools_map, chat_model, and no MCP manager."""

        tm = ToolManager(session_id="sid", service_context=mock_service_context)

        assert tm.session_id == "sid"
        assert tm.service_context is mock_service_context
        assert tm.tools == []
        assert tm.tools_map == {}
        assert tm.chat_model is None
        assert tm._mcp_manager is None
