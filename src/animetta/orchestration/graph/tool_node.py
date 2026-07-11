"""Tool execution node"""

import json
import time as time_module
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from .state import AgentState


def _get_from_config(config: RunnableConfig | None, key: str) -> Any | None:
    """Get value from LangGraph config"""
    if config:
        return config.get("configurable", {}).get(key)
    return None


async def tool_node(
    state: AgentState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """
    Tool execution node

    Input: state["tool_calls"]
    Output: state["tool_results"], state["messages"]
    """
    session_id = state.get("session_id", "unknown")
    tool_calls = state.get("tool_calls")

    if not tool_calls:
        logger.debug(f"[{session_id}] [ToolNode] No tool calls")
        return {"tool_results": [], "tool_calls": None}

    logger.info(f"[{session_id}] [ToolNode] Executing {len(tool_calls)} tool calls")

    tools_map = _get_from_config(config, "tools_map")

    if not tools_map:
        logger.error(f"[{session_id}] [ToolNode] tools_map not configured")
        return {"tool_results": [], "tool_calls": None, "error": "Tool mapping not configured"}

    tool_messages = []
    tool_results = []

    for tool_call in tool_calls:
        tool_id = tool_call.get("id", "unknown")
        tool_name = tool_call.get("name", "unknown")
        tool_args = tool_call.get("args", {})

        logger.info(f"[{session_id}] [ToolNode] Calling tool: {tool_name}({tool_args})")

        t_start = 0.0
        try:
            tool_fn = tools_map.get(tool_name)

            if not tool_fn:
                error_msg = f"Tool not found: {tool_name}"
                logger.error(f"[{session_id}] [ToolNode] {error_msg}")
                tool_messages.append(ToolMessage(content=f"Error: {error_msg}", tool_call_id=tool_id))
                tool_results.append({"error": error_msg})
                continue

            # Execute tool with timing
            t_start = time_module.perf_counter()
            if hasattr(tool_fn, 'ainvoke'):
                result = await tool_fn.ainvoke(tool_args)
            elif hasattr(tool_fn, '_run'):
                result = tool_fn._run(**tool_args)
            else:
                import inspect
                if inspect.iscoroutinefunction(tool_fn):
                    result = await tool_fn(**tool_args)
                else:
                    result = tool_fn(**tool_args)
            duration_s = time_module.perf_counter() - t_start

            # OTel metrics: tool duration + success count
            _record_tool_metrics(tool_name, "success", duration_s)

            result_str = _format_tool_result(result)
            logger.info(f"[{session_id}] [ToolNode] {tool_name} result: {result_str[:100]}...")

            tool_messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
            tool_results.append({"tool": tool_name, "args": tool_args, "result": result})

        except Exception as e:
            duration_s = time_module.perf_counter() - t_start if t_start > 0 else 0
            error_msg = f"Tool execution error: {str(e)}"
            logger.error(f"[{session_id}] [ToolNode] {tool_name} execution failed: {e}")
            tool_messages.append(ToolMessage(content=f"Error: {error_msg}", tool_call_id=tool_id))
            tool_results.append({"tool": tool_name, "args": tool_args, "error": str(e)})

            # OTel metrics: tool error count + duration
            _record_tool_metrics(tool_name, "error", duration_s)

    logger.info(f"[{session_id}] [ToolNode] Completed {len(tool_calls)} tool calls")

    return {
        "messages": tool_messages,
        "tool_results": tool_results,
        "tool_calls": None,
    }


def _format_tool_result(result: Any) -> str:
    """Format tool execution result"""
    if result is None:
        return "(no return value)"
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"[ToolNode] Failed to serialize tool result as JSON: {e}")
            return str(result)
    return str(result)


def _record_tool_metrics(tool_name: str, status: str, duration_s: float) -> None:
    """Record OTel metrics for a tool execution."""
    try:
        tc = get_tool_calls()
        if tc is not None:
            tc.add(1, {"tool_name": tool_name, "status": status})
        td = get_tool_duration()
        if td is not None and duration_s > 0:
            td.observe(duration_s, {"tool_name": tool_name})
    except Exception as e:
        logger.debug(f"[ToolNode] OTel metrics recording failed: {e}")
