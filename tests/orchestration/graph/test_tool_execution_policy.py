from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.runnables import RunnableConfig

from animetta.orchestration.graph.state import create_initial_state
from animetta.orchestration.graph.tool_execution_policy import (
    ToolEffect,
    ToolExecutionPolicy,
    ToolPolicyError,
)
from animetta.orchestration.graph.tool_node import tool_node


def test_minecraft_policy_is_parameter_aware() -> None:
    policy = ToolExecutionPolicy(production=True)

    status = policy.evaluate("mc_connection", {"operation": "status"}, AsyncMock())
    connect = policy.evaluate("mc_connection", {"operation": "connect"}, AsyncMock())

    assert status.effect is ToolEffect.READ_ONLY
    assert status.requires_approval is False
    assert connect.effect is ToolEffect.STATE_CHANGING
    assert connect.requires_approval is True


def test_production_denies_unclassified_mcp_and_filesystem_mutation() -> None:
    policy = ToolExecutionPolicy(production=True)
    unknown = MagicMock(metadata={"tool_source": "mcp", "mcp_server": "remote"})
    filesystem_write = MagicMock(metadata={"tool_source": "mcp", "mcp_server": "filesystem"})

    with pytest.raises(ToolPolicyError, match="no production side-effect classification"):
        policy.evaluate("remote_action", {}, unknown)
    with pytest.raises(ToolPolicyError, match="no production side-effect classification"):
        policy.evaluate("write_file", {"path": "/data/a"}, filesystem_write)


@pytest.mark.asyncio
async def test_read_only_transient_failure_retries_once() -> None:
    tool = MagicMock()
    tool.ainvoke = AsyncMock(side_effect=[ConnectionError("temporary"), "ok"])
    state = create_initial_state(session_id="test")
    state["tool_calls"] = [{"id": "1", "name": "web_search", "args": {"query": "agent"}}]
    config = RunnableConfig(
        configurable={
            "tools_map": {"web_search": tool},
            "tool_execution_policy": ToolExecutionPolicy(production=True),
        }
    )

    result = await tool_node(state, config)

    assert result["tool_results"][0]["result"] == "ok"
    assert result["tool_results"][0]["attempts"] == 2
    assert tool.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_read_only_non_transient_os_error_is_not_retried() -> None:
    tool = MagicMock()
    tool.ainvoke = AsyncMock(side_effect=FileNotFoundError("missing"))
    state = create_initial_state(session_id="test")
    state["tool_calls"] = [{"id": "1", "name": "web_search", "args": {"query": "agent"}}]
    config = RunnableConfig(
        configurable={
            "tools_map": {"web_search": tool},
            "tool_execution_policy": ToolExecutionPolicy(production=True),
        }
    )

    result = await tool_node(state, config)

    assert result["tool_results"][0]["error"] == "missing"
    assert tool.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_minecraft_mutation_is_not_invoked_without_approval() -> None:
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value="changed")
    state = create_initial_state(session_id="test")
    state["tool_calls"] = [
        {"id": "1", "name": "mc_connection", "args": {"operation": "disconnect"}}
    ]
    config = RunnableConfig(
        configurable={
            "tools_map": {"mc_connection": tool},
            "tool_execution_policy": ToolExecutionPolicy(production=True),
        }
    )

    result = await tool_node(state, config)

    assert result["checkpoint_migration_required"] is True
    assert result["tool_results"] == []
    tool.ainvoke.assert_not_awaited()
