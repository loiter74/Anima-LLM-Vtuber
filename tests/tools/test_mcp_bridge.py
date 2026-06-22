from __future__ import annotations

from animetta.tools import MCPManager
from animetta.tools.mcp_bridge import MCPClient, _parse_type, mcp_tool_to_langchain

"""Tests for MCP bridge graceful degradation when Docker is unavailable."""

from unittest.mock import AsyncMock

import pytest


class TestMCPClient:
    """MCPClient handles connection failures gracefully."""

    @pytest.mark.asyncio
    async def test_connect_with_bogus_command_returns_false(self):
        """Connecting with a non-existent command should return False, not crash."""

        client = MCPClient(
            name="test-server",
            transport="stdio",
            command="nonexistent-command-that-will-fail",
            args=["--help"],
        )
        result = await client.connect()
        assert result is False  # Graceful degradation

    @pytest.mark.asyncio
    async def test_disconnect_without_connect(self):
        """Calling disconnect without prior connect should not raise."""

        client = MCPClient(name="test", transport="stdio", command="echo")
        # No connect() called
        await client.disconnect()  # Should not raise

    @pytest.mark.asyncio
    async def test_list_tools_without_session(self):
        """list_tools returns empty list when not connected."""

        client = MCPClient(name="test", transport="stdio", command="echo")
        tools = await client.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_call_tool_without_session(self):
        """call_tool returns None when not connected."""

        client = MCPClient(name="test", transport="stdio", command="echo")
        result = await client.call_tool("test_tool", {"arg": "val"})
        assert result is None


class TestMCPManager:
    """MCPManager handles unavailable Docker gracefully."""

    def test_build_docker_command(self):
        """_build_docker_command constructs a valid docker run command."""

        mgr = MCPManager()
        command, args = mgr._build_docker_command(
            sandbox={
                "image": "anima-mcp-test",
                "mounts": ["./data:/data:rw"],
                "memory": "128m",
                "cpus": "0.5",
            },
            args=["/some/path"],
        )

        assert command == "docker"
        assert "run" in args
        assert "--rm" in args
        assert "--network" in args
        assert "none" in args
        assert "anima-mcp-test" in args
        assert "/some/path" in args

    @pytest.mark.asyncio
    async def test_load_handles_docker_unavailable(self):
        """load() should not crash when Docker is unavailable."""

        mgr = MCPManager()
        # Simulate a Docker-based MCP server config — Docker isn't running,
        # so this should degrade gracefully
        configs = [{
            "name": "filesystem",
            "transport": "stdio",
            "sandbox": {
                "type": "docker",
                "image": "anima-mcp-filesystem",
                "mounts": ["./data:/data:rw"],
            },
            "args": ["/data"],
        }]
        # Should not raise
        tools = await mgr.load(configs)
        assert isinstance(tools, list)


class TestMCPClientInit:
    """MCPClient initialization tests."""

    def test_init_stdio(self):
        client = MCPClient(
            name="test",
            transport="stdio",
            command="echo",
            args=["hello"],
        )
        assert client.name == "test"
        assert client.transport == "stdio"
        assert client.session is None

    def test_init_sse(self):
        client = MCPClient(
            name="sse-test",
            transport="sse",
            url="http://localhost:8080/sse",
        )
        assert client.name == "sse-test"
        assert client.transport == "sse"

    def test_init_streamable_http(self):
        client = MCPClient(
            name="http-test",
            transport="streamable_http",
            url="http://localhost:8080/mcp",
        )
        assert client.name == "http-test"
        assert client.transport == "streamable_http"


class TestMCPToolToLangChain:
    """mcp_tool_to_langchain conversion tests."""

    def test_convert_simple_tool(self):

        client = MCPClient(name="test", transport="stdio", command="echo")

        # Create a mock tool info object
        class MockToolInfo:
            name = "test_tool"
            description = "A test tool"
            inputSchema = {
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                    "param2": {"type": "integer"},
                },
            }

        tool = mcp_tool_to_langchain(client, MockToolInfo())
        assert tool.name == "test_tool"
        assert "A test tool" in tool.description
        assert tool.args_schema is not None
        # Verify schema fields
        schema_fields = tool.args_schema.model_fields
        assert "param1" in schema_fields
        assert "param2" in schema_fields

    def test_convert_tool_no_schema(self):

        client = MCPClient(name="test", transport="stdio", command="echo")

        class MockToolInfoNoSchema:
            name = "no_schema_tool"
            description = "Tool without schema"
            inputSchema = None

        tool = mcp_tool_to_langchain(client, MockToolInfoNoSchema())
        assert tool.name == "no_schema_tool"

    def test_convert_tool_no_description(self):

        client = MCPClient(name="test", transport="stdio", command="echo")

        class MockToolInfoNoDesc:
            name = "no_desc"
            description = None
            inputSchema = {"type": "object", "properties": {}}

        tool = mcp_tool_to_langchain(client, MockToolInfoNoDesc())
        assert tool.name == "no_desc"

    @pytest.mark.asyncio
    async def test_execute_converted_tool(self):

        client = MCPClient(name="test", transport="stdio", command="echo")

        class MockToolInfo:
            name = "echo_tool"
            description = "Echoes input"
            inputSchema = {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
            }

        tool = mcp_tool_to_langchain(client, MockToolInfo())

        # Mock the client.call_tool to test execution flow
        class MockContent:
            text = "echoed: hello"

        class MockResult:
            content = [MockContent()]

        client.call_tool = AsyncMock(return_value=MockResult())
        result = await tool.coroutine(message="hello")
        assert "echoed: hello" in result


class TestMCPManagerAdvanced:
    """Additional MCPManager tests."""

    def test_build_docker_command_with_mount_edge_cases(self):

        mgr = MCPManager()

        # Invalid mount format should be skipped
        command, args = mgr._build_docker_command(
            sandbox={
                "image": "test-image",
                "mounts": ["invalid_format_no_colon"],
                "memory": "256m",
                "cpus": "1.0",
            },
            args=["/data"],
        )
        assert command == "docker"
        assert "test-image" in args

    def test_build_docker_command_defaults(self):

        mgr = MCPManager()

        command, args = mgr._build_docker_command(
            sandbox={},  # Empty sandbox uses defaults
            args=[],
        )
        assert command == "docker"
        assert "anima-mcp-filesystem" in args  # default image
        assert "128m" in args  # default memory
        assert "0.5" in args  # default cpus

    @pytest.mark.asyncio
    async def test_close_all_no_clients(self):

        mgr = MCPManager()
        # Should not raise with no clients
        await mgr.close_all()
        assert len(mgr.clients) == 0
        assert len(mgr.tools) == 0

    @pytest.mark.asyncio
    async def test_load_sse_transport_without_mcp(self):
        """Loading SSE config without mcp package should degrade gracefully."""

        mgr = MCPManager()
        configs = [{
            "name": "sse-server",
            "transport": "sse",
            "url": "http://localhost:8080/sse",
        }]
        tools = await mgr.load(configs)
        assert isinstance(tools, list)

    def test_parse_type_all_types(self):

        assert _parse_type("string") is str
        assert _parse_type("integer") is int
        assert _parse_type("number") is float
        assert _parse_type("boolean") is bool
        assert _parse_type("array") is list
        assert _parse_type("object") is dict
        assert _parse_type("unknown") is str  # fallback
