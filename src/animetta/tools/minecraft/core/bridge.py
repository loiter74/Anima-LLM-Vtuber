"""Streamable HTTP MCP client for the independently owned Minecraft runtime."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
from collections.abc import Callable
from typing import Any

from loguru import logger

from animetta.tools.mcp_bridge import MCPClient

from .config import MinecraftConfig

_bridge: MinecraftMcpBridge | None = None

_RUNTIME_TOOLS = {
    "gamebot_v2_manifest": "gamebot_manifest",
    "gamebot_v2_observe": "gamebot_observe",
    "gamebot_v2_execute_action": "gamebot_execute_action",
    "gamebot_v2_inspect_region": "gamebot_inspect_region",
    "gamebot_v2_inspect_action": "gamebot_inspect_action",
    "gamebot_v2_cancel_action": "gamebot_cancel_action",
    "gamebot_v2_health": "gamebot_health",
    "survival_iron": "review_survival_iron",
}


class MinecraftMcpError(RuntimeError):
    """Raised when mc-mcp is unavailable or returns an invalid result."""


class MinecraftMcpBridge:
    """Own only the MCP client session; mc-mcp owns every external process."""

    def __init__(self, config: MinecraftConfig) -> None:
        self.config = config
        self._client: MCPClient | None = None
        self._running = False
        self._event_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._viewer_callback: Callable[..., Any] | None = None
        self._event_cursor = 0
        self._event_task: asyncio.Task[None] | None = None
        self._connect_lock = asyncio.Lock()

    async def start(self, *, profile: str | None = None, request_id: str) -> dict[str, Any]:
        """Ensure mc-mcp, connect the selected profile, and start event projection."""

        await self._ensure_client()
        result = await self.call_tool(
            "minecraft_connect",
            {
                "profile": profile or self.config.mcp.default_profile,
                "request_id": request_id,
            },
        )
        if result.get("state") != "ready":
            raise MinecraftMcpError(f"MC_MCP_NOT_READY:{result.get('state')}")
        self._running = True
        await self._stop_event_task()
        self._event_task = asyncio.create_task(self._poll_events())
        return result

    async def connection_status(self) -> dict[str, Any]:
        await self._ensure_client()
        return await self.call_tool("minecraft_connection_status", {})

    async def disconnect_runtime(self, *, request_id: str) -> dict[str, Any]:
        await self._ensure_client()
        result = await self.call_tool("minecraft_disconnect", {"request_id": request_id})
        self._running = False
        await self._stop_event_task()
        return result

    async def shutdown_runtime(self, *, request_id: str) -> dict[str, Any]:
        await self._ensure_client()
        result = await self.call_tool("minecraft_shutdown", {"request_id": request_id})
        self._running = False
        await self._stop_event_task()
        return result

    async def reattach_viewer(self, *, request_id: str) -> dict[str, Any]:
        await self._ensure_client()
        return await self.call_tool("minecraft_reattach_viewer", {"request_id": request_id})

    async def run_managed_setup(self, command: str, *, request_id: str) -> dict[str, Any]:
        await self._ensure_client()
        return await self.call_tool(
            "minecraft_managed_setup",
            {"command": command, "request_id": request_id},
        )

    async def send_command(
        self, action: str, params: dict[str, Any] | None = None, timeout: float = 60
    ) -> dict[str, Any]:
        """Adapt the internal GameBot v2 transport protocol to mc-mcp tools."""

        tool_name = _RUNTIME_TOOLS.get(action)
        if tool_name is None:
            return {
                "status": "error",
                "result": {
                    "code": "UNSUPPORTED_MCP_RUNTIME_ACTION",
                    "message": f"Unsupported runtime action: {action}",
                },
            }
        try:
            result = await asyncio.wait_for(
                self.call_tool(tool_name, {"payload": params or {}}),
                timeout=timeout,
            )
        except TimeoutError:
            return {
                "status": "error",
                "result": {"code": "RUNTIME_TIMEOUT", "message": f"{action} timed out"},
            }
        return {"status": "success", "result": result}

    async def close(self) -> None:
        """Close only Anima's MCP session; never mutate MC lifecycle here."""

        self._running = False
        await self._stop_event_task()
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._client is None or self._client.session is None:
            raise MinecraftMcpError("MC_MCP_NOT_CONNECTED")
        failed_client = self._client
        response = await failed_client.call_tool(name, arguments)
        if response is None:
            await self._reconnect_client(failed_client)
            assert self._client is not None
            response = await self._client.call_tool(name, arguments)
            if response is None:
                raise MinecraftMcpError(f"MC_MCP_CALL_FAILED:{name}")
        is_error = bool(getattr(response, "isError", False))
        structured = getattr(response, "structuredContent", None)
        if not isinstance(structured, dict):
            content = getattr(response, "content", ())
            text = next(
                (str(item.text) for item in content if hasattr(item, "text")),
                "{}",
            )
            try:
                structured = json.loads(text)
            except json.JSONDecodeError as exc:
                raise MinecraftMcpError(f"MC_MCP_INVALID_RESPONSE:{name}") from exc
        if is_error:
            error = structured.get("error", structured)
            code = error.get("code", "MC_MCP_ERROR") if isinstance(error, dict) else "MC_MCP_ERROR"
            message = error.get("message", error) if isinstance(error, dict) else error
            raise MinecraftMcpError(f"{code}:{message}")
        return structured

    def set_viewer_callback(self, callback: Callable[..., Any]) -> None:
        self._viewer_callback = callback

    def add_runtime_event_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._event_callbacks.append(callback)

    @property
    def is_running(self) -> bool:
        return self._running

    async def _ensure_client(self) -> None:
        async with self._connect_lock:
            if self._client is not None and self._client.session is not None:
                return
            await self._connect_client()

    async def _reconnect_client(self, failed_client: MCPClient) -> None:
        async with self._connect_lock:
            if self._client is not failed_client and self._client is not None:
                return
            await failed_client.disconnect()
            self._client = None
            await self._connect_client()

    async def _connect_client(self) -> None:
        descriptor = await self._ensure_service()
        token = str(descriptor.get("token", ""))
        if not token:
            raise MinecraftMcpError("MC_MCP_AUTH_TOKEN_MISSING")
        self._client = MCPClient(
            name="minecraft",
            transport="streamable_http",
            url=str(descriptor.get("url") or self.config.mcp.url),
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.config.mcp.request_timeout_seconds,
        )
        if not await self._client.connect():
            self._client = None
            raise MinecraftMcpError("MC_MCP_CONNECTION_FAILED")

    async def _ensure_service(self) -> dict[str, Any]:
        configured_token = os.getenv(self.config.mcp.auth_token_env)
        if configured_token:
            return {
                "url": os.getenv("MC_MCP_URL") or self.config.mcp.url,
                "token": configured_token,
            }
        executable = shutil.which(self.config.mcp.cli_command)
        if executable is None:
            raise MinecraftMcpError(f"MC_MCP_CLI_NOT_FOUND:{self.config.mcp.cli_command}")
        process = await asyncio.create_subprocess_exec(
            executable,
            "service",
            "ensure",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.config.mcp.startup_timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise MinecraftMcpError("MC_MCP_SERVICE_START_TIMEOUT") from None
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise MinecraftMcpError(f"MC_MCP_SERVICE_START_FAILED:{message}")
        try:
            descriptor = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MinecraftMcpError("MC_MCP_DESCRIPTOR_INVALID") from exc
        logger.info("[MinecraftMCP] Local service is ready")
        return descriptor

    async def _poll_events(self) -> None:
        while self._running:
            try:
                page = await self.call_tool(
                    "gamebot_events_since",
                    {"cursor": self._event_cursor, "limit": 100},
                )
                if page.get("overflowed"):
                    logger.warning("[MinecraftMCP] Runtime event cursor overflowed")
                self._event_cursor = int(page.get("next_cursor", self._event_cursor))
                for record in page.get("events", ()):
                    event = record.get("event", {})
                    self._dispatch_event(event)
            except (MinecraftMcpError, TypeError, ValueError) as exc:
                logger.warning(f"[MinecraftMCP] Event polling failed: {exc}")
            await asyncio.sleep(self.config.mcp.event_poll_seconds)

    def _dispatch_event(self, event: dict[str, Any]) -> None:
        for callback in tuple(self._event_callbacks):
            callback(dict(event))
        if event.get("type") == "client_viewer_status" and self._viewer_callback:
            self._viewer_callback("client_viewer_status", dict(event))

    async def _stop_event_task(self) -> None:
        if self._event_task is None:
            return
        self._event_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._event_task
        self._event_task = None


def get_bridge() -> MinecraftMcpBridge | None:
    return _bridge
