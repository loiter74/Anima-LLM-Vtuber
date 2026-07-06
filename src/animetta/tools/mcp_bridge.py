"""
MCP Bridge - Connect to MCP servers and convert tools to LangChain Tools

Supports three transport modes:
- stdio: Local subprocess communication
- sse: Server-Sent Events (HTTP)
- streamable_http: Streamable HTTP (MCP new standard)
"""

import contextlib
from contextlib import AsyncExitStack
from typing import Any

from loguru import logger

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


class MCPClient:
    """Individual MCP server connection"""

    def __init__(self, name: str, transport: str, **kwargs):
        self.name = name
        self.transport = transport
        self._config = kwargs
        self._exit_stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None

    async def connect(self) -> bool:
        """Connect to MCP server"""
        if not MCP_AVAILABLE:
            logger.warning(f"[MCP:{self.name}] mcp package not installed")
            return False

        try:
            self._exit_stack = AsyncExitStack()

            if self.transport == "stdio":
                params = StdioServerParameters(
                    command=self._config["command"],
                    args=self._config.get("args", []),
                    env=self._config.get("env"),
                )
                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )

            elif self.transport == "sse":
                read, write = await self._exit_stack.enter_async_context(
                    sse_client(
                        url=self._config["url"],
                        headers=self._config.get("headers"),
                        timeout=self._config.get("timeout", 5),
                        sse_read_timeout=self._config.get("sse_read_timeout", 300),
                    )
                )

            elif self.transport == "streamable_http":
                streams = await self._exit_stack.enter_async_context(
                    streamable_http_client(url=self._config["url"])
                )
                read, write = streams[0], streams[1]

            else:
                logger.error(f"[MCP:{self.name}] Unsupported transport mode: {self.transport}")
                return False

            self.session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self.session.initialize()
            logger.info(f"[MCP:{self.name}] Connected ({self.transport})")
            return True

        except Exception as e:
            logger.warning(f"[MCP:{self.name}] Connection failed (service may be unavailable): {e}")
            await self.disconnect()
            return False

    async def disconnect(self):
        """Disconnect"""
        if self._exit_stack:
            with contextlib.suppress(RuntimeError):
                # anyio cancel scope cross-task issue (Python 3.13 + anyio compat)
                await self._exit_stack.aclose()
            self._exit_stack = None
            self.session = None
            logger.info(f"[MCP:{self.name}] Disconnected")

    async def list_tools(self) -> list[Any]:
        """Get list of tools provided by the server"""
        if not self.session:
            return []
        try:
            response = await self.session.list_tools()
            tools = response.tools
            logger.info(f"[MCP:{self.name}] Found {len(tools)} tools")
            return tools
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] Failed to get tool list: {e}")
            return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool"""
        if not self.session:
            return None
        try:
            return await self.session.call_tool(name, arguments)
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] Failed to call tool {name}: {e}")
            return None


def _parse_type(type_name: str) -> type:
    """JSON Schema type -> Python type"""
    return {
        "string": str, "integer": int, "number": float,
        "boolean": bool, "array": list, "object": dict,
    }.get(type_name, str)


def mcp_tool_to_langchain(client: MCPClient, tool_info: Any) -> Any:
    """Convert MCP tool to LangChain StructuredTool"""
    from langchain_core.tools import StructuredTool
    from pydantic import create_model

    tool_name = tool_info.name
    description = tool_info.description or ""
    schema = tool_info.inputSchema or {}

    fields = {}
    for prop_name, prop_info in schema.get("properties", {}).items():
        fields[prop_name] = (_parse_type(prop_info.get("type", "string")), ...)

    input_model = create_model(f"{tool_name}_Input", **fields)  # type: ignore[call-overload]

    async def execute(**kwargs):
        result = await client.call_tool(tool_name, kwargs)
        if result and hasattr(result, "content"):
            if isinstance(result.content, list):
                return "\n".join(
                    item.text if hasattr(item, "text") else str(item)
                    for item in result.content
                )
            return str(result.content)
        return str(result) if result else "No result"

    return StructuredTool(
        name=tool_name,
        description=description,
        func=lambda **_kw: "",
        coroutine=execute,
        args_schema=input_model,
    )


class MCPManager:
    """Manage multiple MCP server connections and tools"""

    def __init__(self):
        self.clients: list[MCPClient] = []
        self.tools: list[Any] = []

    def _build_docker_command(
        self, sandbox: dict[str, Any], args: list[str]
    ) -> tuple:
        """
        Build Docker sandbox startup command

        Wraps the original command/args in docker run for OS-level isolation.

        Security boundaries:
        - --network none: Block network access
        - --cap-drop ALL: Remove all Linux capabilities
        - --security-opt no-new-privileges: Prevent privilege escalation
        - --read-only: Read-only root filesystem
        - --pids-limit: Prevent fork bomb
        - --memory/--cpus: Resource limits
        - Run as non-root user (USER mcp in Dockerfile)
        - Only mount specified directories (app-level whitelist + OS-level hard boundary)

        Args:
            sandbox: Sandbox configuration dictionary
            args: Arguments to pass to container ENTRYPOINT

        Returns:
            (command, args) tuple
        """
        from pathlib import Path

        image = sandbox.get("image", "anima-mcp-filesystem")
        mounts = sandbox.get("mounts", [])
        memory = sandbox.get("memory", "128m")
        cpus = sandbox.get("cpus", "0.5")

        docker_args = [
            "run", "--rm", "-i",
            # Network: fully disabled
            "--network", "none",
            # Permissions: minimal
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            # Filesystem: read-only root
            "--read-only",
            "--tmpfs", "/tmp:noexec,nosuid,size=64m",
            # Resource limits
            "--memory", memory,
            "--cpus", cpus,
            "--pids-limit", "64",
            # Cleanup timeout
            "--stop-timeout", "5",
        ]

        # Parse and resolve volume mount paths
        project_root = Path(__file__).parent.parent.parent.parent
        for mount_spec in mounts:
            parts = mount_spec.split(":")
            if len(parts) < 2:
                logger.warning(f"[MCP Docker] Invalid mount format: {mount_spec}")
                continue

            host_path = Path(parts[0])
            if not host_path.is_absolute():
                host_path = project_root / host_path

            container_path = parts[1]
            mode = parts[2] if len(parts) > 2 else "rw"

            resolved = str(host_path.resolve())
            docker_args.extend(["-v", f"{resolved}:{container_path}:{mode}"])
            logger.info(f"[MCP Docker] Mount: {resolved} -> {container_path} ({mode})")

        # Image name
        docker_args.append(image)

        # Arguments to pass to ENTRYPOINT
        docker_args.extend(args)

        return "docker", docker_args

    async def load(self, server_configs: list[dict[str, Any]]) -> list[Any]:
        """Connect to all servers and load tools"""
        if not MCP_AVAILABLE:
            logger.warning("[MCP] mcp package not installed, skipping MCP tool loading")
            return []

        for cfg in server_configs:
            name = cfg.get("name", "unknown")
            transport = cfg.get("transport", "stdio")

            # Extract transport layer parameters
            kwargs = {}
            if transport == "stdio":
                sandbox = cfg.get("sandbox")

                if sandbox and sandbox.get("type") == "docker":
                    # Docker sandbox: wrap original command with docker run
                    command, args = self._build_docker_command(
                        sandbox=sandbox,
                        args=cfg.get("args", []),
                    )
                    kwargs = {"command": command, "args": args}
                else:
                    # Native mode: run directly (npx / node)
                    kwargs = {k: cfg[k] for k in ("command", "args", "env") if k in cfg}

            elif transport in ("sse", "streamable_http"):
                kwargs = {k: cfg[k] for k in ("url", "headers", "timeout") if k in cfg}
                if transport == "sse" and "sse_read_timeout" in cfg:
                    kwargs["sse_read_timeout"] = cfg["sse_read_timeout"]

            client = MCPClient(name=name, transport=transport, **kwargs)
            if await client.connect():
                self.clients.append(client)

                for t in await client.list_tools():
                    try:
                        self.tools.append(mcp_tool_to_langchain(client, t))
                        logger.info(f"[MCP] Loaded tool: {t.name} from {name}")
                    except Exception as e:
                        logger.error(f"[MCP] Failed to convert tool {t.name}: {e}")

        logger.info(f"[MCP] Loaded {len(self.tools)} tools from {len(self.clients)} servers")
        return self.tools

    async def close_all(self):
        """Close all connections"""
        for client in self.clients:
            await client.disconnect()
        self.clients.clear()
        self.tools.clear()
