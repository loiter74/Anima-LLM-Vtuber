"""Streamable HTTP mc-mcp bridge behavior."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from animetta.tools.minecraft.core import bridge as bridge_module
from animetta.tools.minecraft.core.bridge import (
    MinecraftMcpBridge,
    MinecraftMcpError,
    MinecraftMcpRuntime,
    resolve_mc_mcp_runtime,
)
from animetta.tools.minecraft.core.config import MinecraftConfig, MinecraftMcpConfig

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_DIRECT_DEPENDENCIES = tuple(
    sorted(
        json.loads(
            (_REPOSITORY_ROOT / "services" / "mc-mcp" / "package.json").read_text(encoding="utf-8")
        )["dependencies"]
    )
)


def _response(value: dict, *, error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(structuredContent=value, isError=error, content=[])


def _set_repository_cli(
    monkeypatch,
    root: Path,
    *,
    dependencies: bool,
    missing_dependency: str | None = None,
) -> Path:
    cli = root / "src" / "mcp" / "cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    (root / "package.json").write_text(
        json.dumps({"dependencies": dict.fromkeys(_DIRECT_DEPENDENCIES, "*")}),
        encoding="utf-8",
    )
    if dependencies:
        for dependency in _DIRECT_DEPENDENCIES:
            if dependency == missing_dependency:
                continue
            marker = root / "node_modules" / dependency / "package.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(bridge_module, "_REPOSITORY_MC_MCP_ROOT", root)
    monkeypatch.setattr(bridge_module, "_REPOSITORY_MC_MCP_CLI", cli)
    return cli


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8768/mcp",
        "https://localhost/mcp",
        "http://[::1]:8768/mcp",
        "http://host.docker.internal:8768/mcp",
    ],
)
def test_mcp_url_accepts_only_supported_loopback_endpoints(url: str) -> None:
    assert bridge_module.validate_mc_mcp_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/mcp",
        "ftp://127.0.0.1/mcp",
        "http://user:secret@127.0.0.1/mcp",
        "http://127.0.0.1/mcp?token=secret",
        "http://127.0.0.1/mcp#fragment",
        "http://127.0.0.1/health",
        "http://127.0.0.1/mcp/",
    ],
)
def test_mcp_url_rejects_non_loopback_or_credentialed_endpoints(url: str) -> None:
    with pytest.raises(MinecraftMcpError, match="^MC_MCP_URL_INVALID$"):
        bridge_module.validate_mc_mcp_url(url)


def test_environment_token_precedes_cli(monkeypatch) -> None:
    monkeypatch.setenv("ANIMETTA_TEST_MC_TOKEN", "environment")
    monkeypatch.setattr(
        bridge_module.shutil,
        "which",
        Mock(side_effect=AssertionError("CLI discovery must be bypassed")),
    )

    runtime = resolve_mc_mcp_runtime(
        MinecraftMcpConfig(
            auth_token_env="ANIMETTA_TEST_MC_TOKEN",
            cli_command="missing-mc-mcp",
        )
    )

    assert runtime == MinecraftMcpRuntime(token="environment")


def test_configured_multi_argument_cli_is_preserved(monkeypatch) -> None:
    monkeypatch.delenv("MC_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        bridge_module.shutil,
        "which",
        lambda command: "C:/Program Files/nodejs/node.exe" if command == "node" else None,
    )

    runtime = resolve_mc_mcp_runtime(MinecraftMcpConfig(cli_command=("node", "custom/cli.js")))

    assert runtime.command == ("C:/Program Files/nodejs/node.exe", "custom/cli.js")


def test_missing_configured_cli_has_distinct_error(monkeypatch) -> None:
    monkeypatch.delenv("MC_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(bridge_module.shutil, "which", lambda _command: None)

    with pytest.raises(MinecraftMcpError, match="MC_MCP_CLI_NOT_FOUND:custom-mc-mcp"):
        resolve_mc_mcp_runtime(MinecraftMcpConfig(cli_command=("custom-mc-mcp", "--json")))


def test_repository_cli_fallback_uses_node_and_all_argv(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MC_MCP_AUTH_TOKEN", raising=False)
    cli = _set_repository_cli(monkeypatch, tmp_path / "mc-mcp", dependencies=True)
    monkeypatch.setattr(
        bridge_module.shutil,
        "which",
        lambda command: "C:/node/node.exe" if command == "node" else None,
    )

    runtime = resolve_mc_mcp_runtime(MinecraftMcpConfig())

    assert runtime.command == ("C:/node/node.exe", str(cli))


def test_repository_cli_missing_has_distinct_error(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MC_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(bridge_module, "_REPOSITORY_MC_MCP_CLI", tmp_path / "missing-cli.js")
    monkeypatch.setattr(bridge_module.shutil, "which", lambda _command: None)

    with pytest.raises(MinecraftMcpError, match="MC_MCP_REPO_CLI_NOT_FOUND"):
        resolve_mc_mcp_runtime(MinecraftMcpConfig())


def test_repository_cli_requires_node(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MC_MCP_AUTH_TOKEN", raising=False)
    _set_repository_cli(monkeypatch, tmp_path / "mc-mcp", dependencies=True)
    monkeypatch.setattr(bridge_module.shutil, "which", lambda _command: None)

    with pytest.raises(MinecraftMcpError, match="MC_MCP_NODE_NOT_FOUND"):
        resolve_mc_mcp_runtime(MinecraftMcpConfig())


@pytest.mark.parametrize("missing_dependency", _DIRECT_DEPENDENCIES)
def test_repository_cli_requires_every_direct_dependency(
    monkeypatch, tmp_path, missing_dependency: str
) -> None:
    monkeypatch.delenv("MC_MCP_AUTH_TOKEN", raising=False)
    _set_repository_cli(
        monkeypatch,
        tmp_path / "mc-mcp",
        dependencies=True,
        missing_dependency=missing_dependency,
    )
    monkeypatch.setattr(
        bridge_module.shutil,
        "which",
        lambda command: "C:/node/node.exe" if command == "node" else None,
    )

    with pytest.raises(
        MinecraftMcpError,
        match=r"MC_MCP_DEPENDENCIES_NOT_INSTALLED:.*npm ci --prefix services/mc-mcp",
    ):
        resolve_mc_mcp_runtime(MinecraftMcpConfig())


@pytest.mark.asyncio
async def test_config_url_is_rejected_before_client_creation(monkeypatch) -> None:
    monkeypatch.setenv("MC_MCP_AUTH_TOKEN", "secret")
    bridge = MinecraftMcpBridge(
        MinecraftConfig(enabled=True, mcp={"url": "http://example.com/mcp"})
    )

    with (
        patch("animetta.tools.minecraft.core.bridge.MCPClient") as client_factory,
        pytest.raises(MinecraftMcpError, match="^MC_MCP_URL_INVALID$"),
    ):
        await bridge._connect_client()

    client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_environment_url_is_rejected_before_client_creation(monkeypatch) -> None:
    monkeypatch.setenv("MC_MCP_AUTH_TOKEN", "secret")
    monkeypatch.setenv("MC_MCP_URL", "http://localhost/mcp?token=secret")
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))

    with (
        patch("animetta.tools.minecraft.core.bridge.MCPClient") as client_factory,
        pytest.raises(MinecraftMcpError, match="^MC_MCP_URL_INVALID$"),
    ):
        await bridge._connect_client()

    client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_cli_descriptor_url_is_rejected_before_client_creation() -> None:
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._ensure_service = AsyncMock(
        return_value={"url": "https://attacker.example/mcp", "token": "secret"}
    )

    with (
        patch("animetta.tools.minecraft.core.bridge.MCPClient") as client_factory,
        pytest.raises(MinecraftMcpError, match="^MC_MCP_URL_INVALID$"),
    ):
        await bridge._connect_client()

    client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_service_appends_subcommand_to_multi_argv() -> None:
    descriptor = {"url": "http://127.0.0.1:8768/mcp", "token": "generated"}
    process = SimpleNamespace(
        returncode=0,
        communicate=AsyncMock(return_value=(json.dumps(descriptor).encode(), b"")),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))

    with (
        patch(
            "animetta.tools.minecraft.core.bridge.resolve_mc_mcp_runtime",
            return_value=MinecraftMcpRuntime(command=("node.exe", "repo/cli.js")),
        ),
        patch(
            "animetta.tools.minecraft.core.bridge.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ) as spawn,
    ):
        result = await bridge._ensure_service()

    assert result == descriptor
    spawn.assert_awaited_once_with(
        "node.exe",
        "repo/cli.js",
        "service",
        "ensure",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


@pytest.mark.asyncio
async def test_start_uses_profile_and_never_spawns_node_directly(monkeypatch) -> None:
    monkeypatch.setenv("MC_MCP_AUTH_TOKEN", "secret")
    monkeypatch.setenv("MC_MCP_URL", "http://host.docker.internal:18768/mcp")
    client = SimpleNamespace(
        session=object(),
        connect=AsyncMock(return_value=True),
        disconnect=AsyncMock(),
        call_tool=AsyncMock(
            side_effect=[
                _response({"state": "ready", "profile": "external-local"}),
                _response({"events": [], "next_cursor": 0, "overflowed": False}),
            ]
        ),
    )
    with patch(
        "animetta.tools.minecraft.core.bridge.MCPClient", return_value=client
    ) as client_factory:
        bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
        result = await bridge.start(profile="external-local", request_id="connect-1")
        await asyncio.sleep(0)
        await bridge.close()

    assert result["state"] == "ready"
    assert client_factory.call_args.kwargs["url"] == "http://host.docker.internal:18768/mcp"
    assert client_factory.call_args.kwargs["read_timeout"] is None
    assert client.call_tool.await_args_list[0].args == (
        "minecraft_connect",
        {
            "profile": "external-local",
            "request_id": "connect-1",
            "allow_create": False,
            "presentation": {
                "mode": "off",
                "tempo": "normal",
                "seed": "animetta-live-v1",
            },
        },
    )


@pytest.mark.asyncio
async def test_runtime_profile_can_only_reduce_application_presentation_mode() -> None:
    client = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(
            side_effect=[
                _response(
                    {
                        "state": "ready",
                        "profile": "external-review",
                        "bot": {"presentation_mode": "off"},
                    }
                ),
                _response({"events": [], "next_cursor": 0, "overflowed": False}),
            ]
        ),
        disconnect=AsyncMock(),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True, presentation={"mode": "full"}))
    bridge._client = client

    await bridge.start(profile="external-review", request_id="connect-review")
    await asyncio.sleep(0)
    await bridge.close()

    assert bridge.active_presentation_mode == "off"


@pytest.mark.asyncio
async def test_invalid_runtime_presentation_mode_fails_connection() -> None:
    client = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(
            return_value=_response({"state": "ready", "bot": {"presentation_mode": "unexpected"}})
        ),
        disconnect=AsyncMock(),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._client = client

    with pytest.raises(MinecraftMcpError, match="MC_MCP_PRESENTATION_MODE_INVALID"):
        await bridge.start(profile="external-local", request_id="invalid-presentation")


@pytest.mark.asyncio
async def test_managed_creation_requires_explicit_internal_authorization() -> None:
    client = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(return_value=_response({"state": "ready"})),
        disconnect=AsyncMock(),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._client = client

    await bridge.start(
        profile="managed-review",
        request_id="connect-managed",
        allow_server_create=True,
    )
    await bridge.close()

    assert client.call_tool.await_args_list[0].args == (
        "minecraft_connect",
        {
            "profile": "managed-review",
            "request_id": "connect-managed",
            "allow_create": True,
            "presentation": {
                "mode": "off",
                "tempo": "normal",
                "seed": "animetta-live-v1",
            },
        },
    )


@pytest.mark.asyncio
async def test_runtime_action_maps_to_mcp_tool() -> None:
    client = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(return_value=_response({"receipt_id": "receipt-1"})),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._client = client

    result = await bridge.send_command("gamebot_v2_execute_action", {"capability": "goto"})

    assert result == {"status": "success", "result": {"receipt_id": "receipt-1"}}
    client.call_tool.assert_awaited_once_with(
        "gamebot_execute_action", {"payload": {"capability": "goto"}}
    )


@pytest.mark.asyncio
async def test_failed_transport_reconnects_once_and_preserves_call(monkeypatch) -> None:
    first = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(return_value=None),
        disconnect=AsyncMock(),
    )
    second = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(return_value=_response({"state": "ready"})),
        disconnect=AsyncMock(),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._client = first
    monkeypatch.setattr(
        bridge,
        "_connect_client",
        AsyncMock(side_effect=lambda: setattr(bridge, "_client", second)),
    )

    result = await bridge.call_tool("minecraft_connection_status", {})

    assert result == {"state": "ready"}
    first.disconnect.assert_awaited_once()
    second.call_tool.assert_awaited_once_with("minecraft_connection_status", {})


@pytest.mark.asyncio
async def test_mcp_error_is_structured_and_not_retried() -> None:
    client = SimpleNamespace(
        session=object(),
        call_tool=AsyncMock(
            return_value=_response(
                {"ok": False, "error": {"code": "SERVER_UNAVAILABLE", "message": "offline"}},
                error=True,
            )
        ),
    )
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    bridge._client = client

    with pytest.raises(MinecraftMcpError, match="SERVER_UNAVAILABLE:offline"):
        await bridge.call_tool("minecraft_connect", {})

    client.call_tool.assert_awaited_once()


def test_viewer_events_are_projected_without_attachment_logic() -> None:
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    callback = Mock()
    bridge.set_viewer_callback(callback)

    bridge._dispatch_event({"type": "client_viewer_status", "confirmed": True})

    callback.assert_called_once_with(
        "client_viewer_status", {"type": "client_viewer_status", "confirmed": True}
    )


def test_runtime_event_callback_can_be_unsubscribed() -> None:
    bridge = MinecraftMcpBridge(MinecraftConfig(enabled=True))
    callback = Mock()
    unsubscribe = bridge.add_runtime_event_callback(callback)

    bridge._dispatch_event({"type": "action_phase", "phase_sequence": 1})
    unsubscribe()
    unsubscribe()
    bridge._dispatch_event({"type": "action_phase", "phase_sequence": 2})

    callback.assert_called_once_with({"type": "action_phase", "phase_sequence": 1})
