from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.runnables import RunnableConfig

from animetta.orchestration.graph.state import create_initial_state
from animetta.orchestration.graph.tool_execution_policy import ToolExecutionPolicy
from animetta.orchestration.graph.tool_node import tool_node

TOOL_NODE_MODULE = importlib.import_module("animetta.orchestration.graph.tool_node")


class ApprovalObserver:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def before_batch(self, invocations) -> None:
        self.events.append("before_batch")

    async def before_invoke(self, invocation) -> None:
        self.events.append("before_invoke")

    async def after_invoke(self, completion) -> None:
        self.events.append(f"after:{completion.approval_result}")

    async def record_approval(self, invocations, result: str) -> None:
        self.events.append(f"approval:{result}")


def _state():
    state = create_initial_state(session_id="test")
    state["task_id"] = "task-1"
    state["conversation_id"] = "conversation-1"
    state["metadata"] = {
        "runtime_profile": "production",
        "checkpoint_owner_kind": "turn",
        "checkpoint_owner_id": "task-1",
        "checkpoint_retention": "temporary",
    }
    state["tool_calls"] = [
        {"id": "call-1", "name": "mc_connection", "args": {"operation": "connect"}}
    ]
    return state


def _config(tool, observer):
    return RunnableConfig(
        configurable={
            "tools_map": {"mc_connection": tool},
            "tool_execution_policy": ToolExecutionPolicy(production=True),
            "checkpoint_available": True,
            "history_authority": "checkpoint",
            "thread_id": "turn:task-1",
            "tool_invocation_observer": observer,
        }
    )


@pytest.mark.asyncio
async def test_reject_records_resolution_without_observer_or_world_side_effect(
    monkeypatch,
) -> None:
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value="changed")
    observer = ApprovalObserver()

    def reject(payload):
        return {"approval_id": payload["approval_id"], "approved": False}

    monkeypatch.setattr(TOOL_NODE_MODULE, "interrupt", reject)

    result = await tool_node(_state(), _config(tool, observer))

    assert result["tool_results"][0]["error"] == "APPROVAL_REJECTED"
    assert observer.events == ["approval:reject"]
    tool.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_approved_resume_invokes_mutation_exactly_once_after_approval(monkeypatch) -> None:
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value={"request_id": "request-1"})
    observer = ApprovalObserver()

    def approve(payload):
        return {"approval_id": payload["approval_id"], "approved": True}

    monkeypatch.setattr(TOOL_NODE_MODULE, "interrupt", approve)

    result = await tool_node(_state(), _config(tool, observer))

    assert result["tool_results"][0]["result"] == {"request_id": "request-1"}
    assert observer.events == [
        "approval:approve",
        "before_batch",
        "before_invoke",
        "after:approve",
    ]
    tool.ainvoke.assert_awaited_once_with({"operation": "connect"})


@pytest.mark.asyncio
async def test_volatile_mutation_requests_durable_migration_without_side_effects() -> None:
    tool = MagicMock()
    tool.ainvoke = AsyncMock(return_value="changed")
    observer = ApprovalObserver()
    config = _config(tool, observer)
    config["configurable"]["history_authority"] = "conversation_registry"

    result = await tool_node(_state(), config)

    assert result["checkpoint_migration_required"] is True
    assert result["tool_calls"] == _state()["tool_calls"]
    assert observer.events == []
    tool.ainvoke.assert_not_awaited()
