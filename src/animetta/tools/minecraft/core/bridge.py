"""Streamable HTTP MCP client for the independently owned Minecraft runtime."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from loguru import logger
from pydantic import ValidationError

from animetta.tools.mcp_bridge import MCPClient

from .config import MinecraftConfig, MinecraftMcpConfig

_bridge: MinecraftMcpBridge | None = None

_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_REPOSITORY_MC_MCP_ROOT = _REPOSITORY_ROOT / "services" / "mc-mcp"
_REPOSITORY_MC_MCP_CLI = _REPOSITORY_MC_MCP_ROOT / "src" / "mcp" / "cli.js"
_ALLOWED_MC_MCP_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "host.docker.internal"})

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


@dataclass(frozen=True, slots=True)
class MinecraftMcpRuntime:
    """Resolved authentication or CLI command used to reach mc-mcp."""

    token: str | None = None
    command: tuple[str, ...] | None = None


def validate_mc_mcp_url(value: object) -> str:
    """Return a loopback Streamable HTTP MCP URL or reject it."""

    try:
        url = str(value).strip()
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        _ = parsed.port
    except (TypeError, ValueError):
        raise MinecraftMcpError("MC_MCP_URL_INVALID") from None
    if (
        not url
        or parsed.scheme.lower() not in {"http", "https"}
        or hostname not in _ALLOWED_MC_MCP_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/mcp"
        or parsed.query
        or parsed.fragment
    ):
        raise MinecraftMcpError("MC_MCP_URL_INVALID")
    return url


def resolve_mc_mcp_runtime(
    config: MinecraftMcpConfig | dict[str, Any],
) -> MinecraftMcpRuntime:
    """Resolve an environment token or executable command for ``service ensure``."""

    try:
        mcp = (
            config
            if isinstance(config, MinecraftMcpConfig)
            else MinecraftMcpConfig.model_validate(config)
        )
    except ValidationError as exc:
        raise MinecraftMcpError(f"MC_MCP_CONFIG_INVALID:{exc.errors()[0]['msg']}") from exc
    environment_token = os.getenv(mcp.auth_token_env, "").strip() if mcp.auth_token_env else ""
    if environment_token:
        return MinecraftMcpRuntime(token=environment_token)

    command = _parse_cli_command(mcp.cli_command)
    executable = _find_executable(command[0])
    if executable:
        return MinecraftMcpRuntime(command=(executable, *command[1:]))
    if command != ("mc-mcp",):
        raise MinecraftMcpError(f"MC_MCP_CLI_NOT_FOUND:{command[0]}")
    return MinecraftMcpRuntime(command=_resolve_repository_cli())


def _parse_cli_command(command: str | tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(command, str):
        return command
    try:
        parts = tuple(shlex.split(command, posix=os.name != "nt"))
    except ValueError as exc:
        raise MinecraftMcpError("MC_MCP_CLI_COMMAND_INVALID") from exc
    if os.name == "nt":
        parts = tuple(_strip_matching_quotes(part) for part in parts)
    if not parts:
        raise MinecraftMcpError("MC_MCP_CLI_COMMAND_INVALID")
    return parts


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _find_executable(command: str) -> str | None:
    executable = shutil.which(command)
    if executable:
        return executable
    candidate = Path(command).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def _resolve_repository_cli() -> tuple[str, ...]:
    if not _REPOSITORY_MC_MCP_CLI.is_file():
        raise MinecraftMcpError(f"MC_MCP_REPO_CLI_NOT_FOUND:{_REPOSITORY_MC_MCP_CLI}")
    node = shutil.which("node")
    if node is None:
        raise MinecraftMcpError(
            "MC_MCP_NODE_NOT_FOUND:Install Node.js and ensure 'node' is on PATH"
        )
    missing_dependencies = _missing_repository_dependencies()
    if missing_dependencies:
        raise MinecraftMcpError(
            "MC_MCP_DEPENDENCIES_NOT_INSTALLED:"
            f"Missing {', '.join(missing_dependencies)}; "
            "run 'npm ci --prefix services/mc-mcp' from the repository root"
        )
    return node, str(_REPOSITORY_MC_MCP_CLI)


def _missing_repository_dependencies() -> tuple[str, ...]:
    package_path = _REPOSITORY_MC_MCP_ROOT / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        dependencies = package["dependencies"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError):
        raise MinecraftMcpError("MC_MCP_REPO_PACKAGE_INVALID") from None
    if not isinstance(dependencies, dict) or not all(
        isinstance(name, str) and _valid_package_name(name) for name in dependencies
    ):
        raise MinecraftMcpError("MC_MCP_REPO_PACKAGE_INVALID")
    node_modules = _REPOSITORY_MC_MCP_ROOT / "node_modules"
    return tuple(
        sorted(
            name
            for name in dependencies
            if not (node_modules.joinpath(*name.split("/")) / "package.json").is_file()
        )
    )


def _valid_package_name(name: str) -> bool:
    parts = name.split("/")
    expected_parts = 2 if name.startswith("@") else 1
    return len(parts) == expected_parts and all(part not in {"", ".", ".."} for part in parts)


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

    async def start(
        self,
        *,
        profile: str | None = None,
        request_id: str,
        allow_server_create: bool = False,
    ) -> dict[str, Any]:
        """Ensure mc-mcp, connect the selected profile, and start event projection."""

        await self._ensure_client()
        result = await self.call_tool(
            "minecraft_connect",
            {
                "profile": profile or self.config.mcp.default_profile,
                "request_id": request_id,
                "allow_create": allow_server_create,
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
            result = await self.call_tool(
                tool_name,
                {"payload": params or {}},
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

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.wait_for(
            self._call_tool(name, arguments),
            timeout=timeout or self.config.mcp.request_timeout_seconds,
        )

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
        url = validate_mc_mcp_url(descriptor.get("url") or self.config.mcp.url)
        token = str(descriptor.get("token", ""))
        if not token:
            raise MinecraftMcpError("MC_MCP_AUTH_TOKEN_MISSING")
        self._client = MCPClient(
            name="minecraft",
            transport="streamable_http",
            url=url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.config.mcp.request_timeout_seconds,
            read_timeout=None,
        )
        if not await self._client.connect():
            self._client = None
            raise MinecraftMcpError("MC_MCP_CONNECTION_FAILED")

    async def _ensure_service(self) -> dict[str, Any]:
        runtime = resolve_mc_mcp_runtime(self.config.mcp)
        if runtime.token:
            return {
                "url": os.getenv("MC_MCP_URL") or self.config.mcp.url,
                "token": runtime.token,
            }
        if runtime.command is None:
            raise MinecraftMcpError("MC_MCP_CLI_COMMAND_INVALID")
        process = await asyncio.create_subprocess_exec(
            *runtime.command,
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
            if not message:
                message = f"process exited with code {process.returncode}"
            raise MinecraftMcpError(f"MC_MCP_SERVICE_START_FAILED:{message}")
        try:
            descriptor = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MinecraftMcpError("MC_MCP_DESCRIPTOR_INVALID") from exc
        if not isinstance(descriptor, dict):
            raise MinecraftMcpError("MC_MCP_DESCRIPTOR_INVALID")
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
