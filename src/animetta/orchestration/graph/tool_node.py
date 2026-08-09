"""Tool execution node"""

import json
from contextlib import nullcontext
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger

from animetta.services.llm.minecraft_tool_policy import (
    MAX_MISSION_ATTEMPTS,
    is_mission_call,
    is_repairable_mission_error,
    mission_failure_count,
    mission_problem,
)

from .state import AgentState
from .tool_observation import ToolInvocation, ToolInvocationCompletion, ToolInvocationObserver


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
    observer: ToolInvocationObserver | None = _get_from_config(config, "tool_invocation_observer")

    if not tools_map:
        logger.error(f"[{session_id}] [ToolNode] tools_map not configured")
        return {"tool_results": [], "tool_calls": None, "error": "Tool mapping not configured"}

    tool_messages = []
    tool_results = []
    prior_mission_failures = mission_failure_count(state.get("messages", ()))

    invocations = tuple(
        ToolInvocation(
            tool_call_id=str(tool_call.get("id", "unknown")),
            tool_name=str(tool_call.get("name", "unknown")),
            arguments=dict(tool_call.get("args", {})),
            session_id=str(session_id),
            conversation_id=state.get("conversation_id"),
        )
        for tool_call in tool_calls
    )
    await _notify_observer_before_batch(observer, invocations)

    for tool_call, invocation in zip(tool_calls, invocations, strict=True):
        tool_id = tool_call.get("id", "unknown")
        tool_name = tool_call.get("name", "unknown")
        tool_args = tool_call.get("args", {})

        logger.info(f"[{session_id}] [ToolNode] Calling tool: {tool_name}({tool_args})")

        mission_call = is_mission_call(tool_name, tool_args)
        if mission_call and prior_mission_failures >= MAX_MISSION_ATTEMPTS:
            content, additional_kwargs = mission_problem(
                error=None,
                attempt=prior_mission_failures,
                exhausted=True,
            )
            tool_messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=tool_id,
                    additional_kwargs=additional_kwargs,
                )
            )
            tool_results.append(
                {
                    "tool": tool_name,
                    "args": tool_args,
                    "error": "MC_MISSION_REPAIR_EXHAUSTED",
                }
            )
            continue

        try:
            tool_fn = tools_map.get(tool_name)

            if not tool_fn:
                error_msg = f"Tool not found: {tool_name}"
                logger.error(f"[{session_id}] [ToolNode] {error_msg}")
                tool_messages.append(
                    ToolMessage(content=f"Error: {error_msg}", tool_call_id=tool_id)
                )
                tool_results.append({"error": error_msg})
                continue

            if observer is not None:
                await observer.before_invoke(invocation)

            try:
                if hasattr(tool_fn, "ainvoke"):
                    with _trusted_tool_scope(tool_name, state):
                        result = await tool_fn.ainvoke(tool_args)
                elif hasattr(tool_fn, "_run"):
                    with _trusted_tool_scope(tool_name, state):
                        result = tool_fn._run(**tool_args)
                else:
                    import inspect

                    with _trusted_tool_scope(tool_name, state):
                        if inspect.iscoroutinefunction(tool_fn):
                            result = await tool_fn(**tool_args)
                        else:
                            result = tool_fn(**tool_args)
            except Exception as exc:
                await _notify_observer_after(
                    observer,
                    ToolInvocationCompletion(
                        invocation=invocation,
                        result=None,
                        error=str(exc),
                    ),
                )
                raise
            await _notify_observer_after(
                observer,
                ToolInvocationCompletion(
                    invocation=invocation,
                    result=result,
                    error=None,
                ),
            )
            result_str = _format_tool_result(result)
            logger.info(f"[{session_id}] [ToolNode] {tool_name} result: {result_str[:100]}...")

            tool_messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
            tool_results.append({"tool": tool_name, "args": tool_args, "result": result})

        except Exception as e:
            if mission_call and is_repairable_mission_error(e):
                prior_mission_failures += 1
                content, additional_kwargs = mission_problem(
                    error=e,
                    attempt=prior_mission_failures,
                )
                logger.error(f"[{session_id}] [ToolNode] {tool_name} validation failed: {e}")
                tool_messages.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=tool_id,
                        additional_kwargs=additional_kwargs,
                    )
                )
                tool_results.append(
                    {
                        "tool": tool_name,
                        "args": tool_args,
                        "error": "MC_MISSION_SCHEMA_INVALID",
                    }
                )
                continue
            error_msg = f"Tool execution error: {str(e)}"
            logger.error(f"[{session_id}] [ToolNode] {tool_name} execution failed: {e}")
            tool_messages.append(ToolMessage(content=f"Error: {error_msg}", tool_call_id=tool_id))
            tool_results.append({"tool": tool_name, "args": tool_args, "error": str(e)})

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


async def _notify_observer_after(
    observer: ToolInvocationObserver | None,
    completion: ToolInvocationCompletion,
) -> None:
    """Observation failure cannot overwrite a tool outcome after world mutation."""

    if observer is None:
        return
    try:
        await observer.after_invoke(completion)
    except Exception as exc:
        logger.error(
            "[{}] [ToolNode] Tool observer failed after {}: {}",
            completion.invocation.session_id,
            completion.invocation.tool_name,
            exc,
        )


async def _notify_observer_before_batch(
    observer: ToolInvocationObserver | None,
    invocations: tuple[ToolInvocation, ...],
) -> None:
    """Let strict observers reject an ambiguous batch before any mutation."""

    if observer is None:
        return
    before_batch = getattr(observer, "before_batch", None)
    if before_batch is not None:
        await before_batch(invocations)


def _trusted_tool_scope(tool_name: str, state: AgentState):
    if tool_name not in {"mc_connection", "mc_operate_bot"}:
        return nullcontext()
    from animetta.tools.minecraft.core.tools import bind_minecraft_caller_scope

    identity = state.get("conversation_id") or state.get("session_id", "unknown")
    return bind_minecraft_caller_scope(f"conversation:{identity}")
