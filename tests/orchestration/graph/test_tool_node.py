from __future__ import annotations

"""Tests for tool execution node."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.types import RunnableConfig

from animetta.orchestration.graph import tool_node
from animetta.orchestration.graph.state import create_initial_state


class TestToolNode:
    """Tool node: executes tool_calls and routes results back to state."""

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_empty(self):
        """When tool_calls is None or empty, return empty results."""

        state = create_initial_state(session_id="test")
        state["tool_calls"] = None
        result = await tool_node(state)

        assert result["tool_results"] == []
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_no_tool_calls_empty_list(self):
        """Empty list of tool_calls also returns empty results."""

        state = create_initial_state(session_id="test")
        state["tool_calls"] = []
        result = await tool_node(state)

        assert result["tool_results"] == []
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_no_tools_map_in_config_returns_error(self):
        """When tools_map is missing from config, return error."""

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [{"id": "1", "name": "calculator", "args": {}}]
        config = RunnableConfig(configurable={})
        result = await tool_node(state, config)

        assert result["tool_calls"] is None
        assert result["tool_results"] == []
        assert "not configured" in (result.get("error") or "")

    @pytest.mark.asyncio
    async def test_successful_ainvoke_tool(self):
        """Tool with ainvoke method executes asynchronously."""

        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(return_value={"result": 42})

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [{"id": "call_1", "name": "calculator", "args": {"x": 6, "y": 7}}]
        config = RunnableConfig(
            configurable={
                "tools_map": {"calculator": mock_tool},
            }
        )
        result = await tool_node(state, config)

        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["tool"] == "calculator"
        assert result["tool_results"][0]["result"] == {"result": 42}
        assert result["tool_calls"] is None
        assert len(result["messages"]) == 1
        content = result["messages"][0].content
        assert "42" in content
        assert result["messages"][0].tool_call_id == "call_1"

    @pytest.mark.asyncio
    async def test_tool_invocation_observer_wraps_the_real_tool_call(self):
        """A trusted observer sees the exact call before and result after execution."""

        events: list[tuple[str, object]] = []

        class ObservedTool:
            async def ainvoke(self, args):
                events.append(("tool", dict(args)))
                return {"mission_id": "mission-001"}

        class Observer:
            async def before_invoke(self, invocation):
                events.append(
                    (
                        "before",
                        (
                            invocation.tool_call_id,
                            invocation.tool_name,
                            invocation.arguments,
                            invocation.conversation_id,
                        ),
                    )
                )

            async def after_invoke(self, completion):
                events.append(
                    (
                        "after",
                        (
                            completion.invocation.tool_call_id,
                            completion.result,
                            completion.error,
                        ),
                    )
                )

        state = create_initial_state(
            session_id="test",
            conversation_id="conversation-001",
        )
        state["tool_calls"] = [
            {
                "id": "call-mission-001",
                "name": "mc_execute",
                "args": {"request_id": "request-001", "kind": "mission"},
            }
        ]
        config = RunnableConfig(
            configurable={
                "tools_map": {"mc_execute": ObservedTool()},
                "tool_invocation_observer": Observer(),
            }
        )

        result = await tool_node(state, config)

        assert result["tool_results"][0]["result"] == {"mission_id": "mission-001"}
        assert events == [
            (
                "before",
                (
                    "call-mission-001",
                    "mc_execute",
                    {"request_id": "request-001", "kind": "mission"},
                    "conversation-001",
                ),
            ),
            ("tool", {"request_id": "request-001", "kind": "mission"}),
            (
                "after",
                (
                    "call-mission-001",
                    {"mission_id": "mission-001"},
                    None,
                ),
            ),
        ]

    @pytest.mark.asyncio
    async def test_observer_failure_after_tool_does_not_erase_real_result(self):
        """A reporting failure after mutation must not rewrite tool success."""

        class ObservedTool:
            async def ainvoke(self, _args):
                return {"mission_id": "mission-committed"}

        class Observer:
            async def before_invoke(self, _invocation):
                return None

            async def after_invoke(self, _completion):
                raise RuntimeError("evidence sink unavailable")

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [
            {
                "id": "call-committed",
                "name": "mc_execute",
                "args": {"request_id": "request-committed", "kind": "mission"},
            }
        ]
        config = RunnableConfig(
            configurable={
                "tools_map": {"mc_execute": ObservedTool()},
                "tool_invocation_observer": Observer(),
            }
        )

        result = await tool_node(state, config)

        assert result["tool_results"] == [
            {
                "tool": "mc_execute",
                "args": {"request_id": "request-committed", "kind": "mission"},
                "result": {"mission_id": "mission-committed"},
            }
        ]
        assert result["messages"][0].content == '{\n  "mission_id": "mission-committed"\n}'

    @pytest.mark.asyncio
    async def test_tool_not_found_returns_error(self):
        """Unknown tool name returns an error result."""

        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(return_value="ok")

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [{"id": "call_1", "name": "nonexistent_tool", "args": {}}]
        config = RunnableConfig(configurable={"tools_map": {"calculator": mock_tool}})
        result = await tool_node(state, config)

        assert len(result["tool_results"]) == 1
        assert "error" in result["tool_results"][0]
        assert "not found" in result["tool_results"][0]["error"]
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_tool_execution_error_handled_gracefully(self):
        """When a tool raises, error is captured without crashing the node."""

        failing_tool = MagicMock()
        failing_tool.ainvoke = AsyncMock(side_effect=ValueError("division by zero"))

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [{"id": "call_1", "name": "bad_tool", "args": {}}]
        config = RunnableConfig(configurable={"tools_map": {"bad_tool": failing_tool}})
        result = await tool_node(state, config)

        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["tool"] == "bad_tool"
        assert "division by zero" in result["tool_results"][0]["error"]
        assert result["tool_calls"] is None
        # A ToolMessage should still be produced
        assert len(result["messages"]) == 1
        assert "Error" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        """Multiple tool calls are executed sequentially and all results returned."""

        tool_a = MagicMock()
        tool_a.ainvoke = AsyncMock(return_value="result_a")

        tool_b = MagicMock()
        tool_b.ainvoke = AsyncMock(return_value="result_b")

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [
            {"id": "call_1", "name": "tool_a", "args": {}},
            {"id": "call_2", "name": "tool_b", "args": {"key": "val"}},
        ]
        config = RunnableConfig(configurable={"tools_map": {"tool_a": tool_a, "tool_b": tool_b}})
        result = await tool_node(state, config)

        assert len(result["tool_results"]) == 2
        assert result["tool_results"][0]["tool"] == "tool_a"
        assert result["tool_results"][1]["tool"] == "tool_b"
        assert result["tool_results"][0]["result"] == "result_a"
        assert result["tool_results"][1]["result"] == "result_b"
        assert len(result["messages"]) == 2
        tool_a.ainvoke.assert_awaited_once()
        tool_b.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_tool_via_run_method(self):
        """Tool with _run method is called synchronously."""

        class SyncRunTool:
            """A tool-like object that has _run but not ainvoke."""

            def _run(self, x):
                return f"sync_result_{x}"

        sync_tool = SyncRunTool()

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [{"id": "call_1", "name": "sync_tool", "args": {"x": 42}}]
        config = RunnableConfig(configurable={"tools_map": {"sync_tool": sync_tool}})
        result = await tool_node(state, config)

        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["result"] == "sync_result_42"

    @pytest.mark.asyncio
    async def test_sync_callable_tool(self):
        """A plain synchronous callable is called directly."""

        def plain_tool(greeting: str) -> str:
            return f"{greeting}, world!"

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [
            {"id": "call_1", "name": "plain_tool", "args": {"greeting": "Hello"}}
        ]
        config = RunnableConfig(configurable={"tools_map": {"plain_tool": plain_tool}})
        result = await tool_node(state, config)

        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["result"] == "Hello, world!"

    @pytest.mark.asyncio
    async def test_async_callable_tool(self):
        """A plain async function is awaited directly."""

        async def async_plain_tool(text: str) -> str:
            return f"async: {text}"

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [{"id": "call_1", "name": "async_fn", "args": {"text": "hello"}}]
        config = RunnableConfig(configurable={"tools_map": {"async_fn": async_plain_tool}})
        result = await tool_node(state, config)

        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["result"] == "async: hello"

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self):
        """Partial failures collect both results and errors."""

        good_tool = MagicMock()
        good_tool.ainvoke = AsyncMock(return_value="ok")

        bad_tool = MagicMock()
        bad_tool.ainvoke = AsyncMock(side_effect=RuntimeError("fail"))

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [
            {"id": "c1", "name": "good", "args": {}},
            {"id": "c2", "name": "bad", "args": {}},
        ]
        config = RunnableConfig(configurable={"tools_map": {"good": good_tool, "bad": bad_tool}})
        result = await tool_node(state, config)

        assert len(result["tool_results"]) == 2
        assert result["tool_results"][0]["result"] == "ok"
        assert "error" in result["tool_results"][1]
        assert "fail" in result["tool_results"][1]["error"]
        assert len(result["messages"]) == 2
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_none_result_formatted(self):
        """Tool returning None should produce '(no return value)' string."""

        null_tool = MagicMock()
        null_tool.ainvoke = AsyncMock(return_value=None)

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [{"id": "c1", "name": "null_tool", "args": {}}]
        config = RunnableConfig(configurable={"tools_map": {"null_tool": null_tool}})
        result = await tool_node(state, config)

        assert result["tool_results"][0]["result"] is None
        assert "(no return value)" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_dict_result_json_serialized(self):
        """Dict results should be JSON-serialized in the message."""

        dict_tool = MagicMock()
        dict_tool.ainvoke = AsyncMock(return_value={"a": 1, "b": [2, 3]})

        state = create_initial_state(session_id="test")
        state["tool_calls"] = [{"id": "c1", "name": "dict_tool", "args": {}}]
        config = RunnableConfig(configurable={"tools_map": {"dict_tool": dict_tool}})
        result = await tool_node(state, config)

        assert result["tool_results"][0]["result"] == {"a": 1, "b": [2, 3]}
        assert '"a": 1' in result["messages"][0].content
