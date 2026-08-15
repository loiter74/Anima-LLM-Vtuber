"""Tool execution node"""

import asyncio
import hashlib
import json
import time
from contextlib import nullcontext
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from loguru import logger

from animetta.services.llm.minecraft_tool_policy import (
    MAX_MISSION_ATTEMPTS,
    is_mission_call,
    is_repairable_mission_error,
    mission_failure_count,
    mission_problem,
)

from .state import AgentState
from .tool_execution_policy import (
    ToolExecutionDecision,
    ToolExecutionPolicy,
    ToolPolicyError,
    is_transient_tool_error,
)
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
    observer: ToolInvocationObserver | None = _get_from_config(
        config,
        "effective_tool_invocation_observer",
    ) or _get_from_config(config, "tool_invocation_observer")
    policy = _get_from_config(config, "tool_execution_policy")
    if not isinstance(policy, ToolExecutionPolicy):
        profile = str(state.get("metadata", {}).get("runtime_profile") or "test")
        policy = ToolExecutionPolicy(production=profile == "production")

    if not tools_map:
        logger.error(f"[{session_id}] [ToolNode] tools_map not configured")
        return {"tool_results": [], "tool_calls": None, "error": "Tool mapping not configured"}

    tool_messages = []
    tool_results = []
    prior_mission_failures = mission_failure_count(state.get("messages", ()))

    invocations = tuple(
        _tool_invocation(tool_call, tools_map=tools_map, state=state) for tool_call in tool_calls
    )
    decisions_or_error = _preflight_decisions(tool_calls, tools_map, policy)
    if isinstance(decisions_or_error, ToolPolicyError):
        await _notify_policy_failure(observer, invocations, decisions_or_error.code)
        return _batch_failure(tool_calls, decisions_or_error.code, str(decisions_or_error))
    decisions = decisions_or_error
    approval_result: str | None = None
    if any(decision is not None and decision.requires_approval for decision in decisions):
        if _get_from_config(config, "history_authority") != "checkpoint":
            return {
                "tool_results": [],
                "tool_calls": tool_calls,
                "checkpoint_migration_required": True,
            }
        if _get_from_config(config, "checkpoint_available") is not True:
            return _batch_failure(
                tool_calls,
                "CHECKPOINT_UNAVAILABLE",
                "Durable approval execution is unavailable",
            )
        approval = _approval_payload(tool_calls, state, config)
        resolution = interrupt(approval)
        if (
            not isinstance(resolution, dict)
            or resolution.get("approval_id") != approval["approval_id"]
        ):
            await _notify_approval(observer, invocations, "reject")
            return _batch_failure(
                tool_calls,
                "APPROVAL_REJECTED",
                "Approval response did not match the pending request",
            )
        if resolution.get("approved") is not True:
            await _notify_approval(observer, invocations, "reject")
            return _batch_failure(tool_calls, "APPROVAL_REJECTED", "Operator rejected the tools")
        approval_result = "approve"
        await _notify_approval(observer, invocations, approval_result)
    await _notify_observer_before_batch(observer, invocations)

    for tool_call, invocation, decision in zip(tool_calls, invocations, decisions, strict=True):
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

            assert decision is not None

            if observer is not None:
                await observer.before_invoke(invocation)

            try:
                result, attempts = await _execute_with_policy(
                    tool_fn,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    state=state,
                    decision=decision,
                )
            except asyncio.CancelledError as exc:
                await _notify_observer_after(
                    observer,
                    ToolInvocationCompletion(
                        invocation=invocation,
                        result=None,
                        error=str(exc) or "cancelled",
                        cancelled=True,
                        approval_result=approval_result,
                        error_code="CANCELLED",
                        tool_effect=decision.effect.value,
                    ),
                )
                raise
            except Exception as exc:
                await _notify_observer_after(
                    observer,
                    ToolInvocationCompletion(
                        invocation=invocation,
                        result=None,
                        error=str(exc),
                        approval_result=approval_result,
                        error_code=_tool_error_code(exc),
                        tool_effect=decision.effect.value,
                    ),
                )
                raise
            await _notify_observer_after(
                observer,
                ToolInvocationCompletion(
                    invocation=invocation,
                    result=result,
                    error=None,
                    retry_count=attempts - 1,
                    approval_result=approval_result,
                    tool_effect=decision.effect.value,
                ),
            )
            result_str = _format_tool_result(result)
            logger.info(f"[{session_id}] [ToolNode] {tool_name} result: {result_str[:100]}...")

            tool_messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
            tool_result = {"tool": tool_name, "args": tool_args, "result": result}
            if attempts > 1:
                tool_result["attempts"] = attempts
            tool_results.append(tool_result)

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
            code = (
                e.code
                if isinstance(e, ToolPolicyError)
                else "TOOL_TIMEOUT"
                if isinstance(e, TimeoutError)
                else None
            )
            error_msg = f"Tool execution error: {str(e)}"
            logger.error(f"[{session_id}] [ToolNode] {tool_name} execution failed: {e}")
            tool_messages.append(ToolMessage(content=f"Error: {error_msg}", tool_call_id=tool_id))
            tool_results.append(
                {
                    "tool": tool_name,
                    "args": tool_args,
                    "error": code or str(e),
                }
            )

    logger.info(f"[{session_id}] [ToolNode] Completed {len(tool_calls)} tool calls")

    return {
        "messages": tool_messages,
        "tool_results": tool_results,
        "tool_calls": None,
        "checkpoint_migration_required": False,
    }


def _preflight_decisions(
    tool_calls: list[dict[str, Any]],
    tools_map: dict[str, Any],
    policy: ToolExecutionPolicy,
) -> list[ToolExecutionDecision | None] | ToolPolicyError:
    decisions: list[ToolExecutionDecision | None] = []
    try:
        for tool_call in tool_calls:
            tool_name = str(tool_call.get("name") or "unknown")
            tool_fn = tools_map.get(tool_name)
            decisions.append(
                policy.evaluate(tool_name, dict(tool_call.get("args") or {}), tool_fn)
                if tool_fn is not None
                else None
            )
    except ToolPolicyError as exc:
        return exc
    return decisions


def _approval_payload(
    tool_calls: list[dict[str, Any]],
    state: AgentState,
    config: RunnableConfig | None,
) -> dict[str, Any]:
    thread_id = str(_get_from_config(config, "thread_id") or "")
    identity = "|".join(str(call.get("id") or "") for call in tool_calls)
    approval_id = hashlib.sha256(f"{thread_id}|{identity}".encode()).hexdigest()[:32]
    return {
        "schema_version": 1,
        "approval_id": approval_id,
        "thread_id": thread_id,
        "task_id": state.get("task_id"),
        "session_id": state.get("session_id"),
        "conversation_id": state.get("conversation_id"),
        "owner_kind": state.get("metadata", {}).get("checkpoint_owner_kind", "turn"),
        "owner_id": state.get("metadata", {}).get("checkpoint_owner_id") or state.get("task_id"),
        "retention": state.get("metadata", {}).get("checkpoint_retention", "temporary"),
        "expires_at": int(time.time()) + 120,
        "tools": [
            {
                "tool_call_id": str(call.get("id") or "unknown"),
                "name": str(call.get("name") or "unknown"),
                "arguments": dict(call.get("args") or {}),
            }
            for call in tool_calls
        ],
    }


def _batch_failure(
    tool_calls: list[dict[str, Any]],
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {code}: {message}",
                tool_call_id=str(call.get("id") or "unknown"),
            )
            for call in tool_calls
        ],
        "tool_results": [
            {
                "tool": str(call.get("name") or "unknown"),
                "args": dict(call.get("args") or {}),
                "error": code,
            }
            for call in tool_calls
        ],
        "tool_calls": None,
    }


async def _execute_with_policy(
    tool_fn: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    state: AgentState,
    decision: ToolExecutionDecision,
) -> tuple[Any, int]:
    last_error: BaseException | None = None
    for attempt in range(1, decision.max_attempts + 1):
        transient = False
        try:
            async with asyncio.timeout(decision.timeout_seconds):
                result = await _invoke_tool(tool_fn, tool_name, tool_args, state)
            return result, attempt
        except TimeoutError:
            last_error = ToolPolicyError(
                "TOOL_TIMEOUT",
                f"Tool '{tool_name}' exceeded {decision.timeout_seconds:g} seconds",
            )
            transient = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            transient = is_transient_tool_error(exc)
        if attempt >= decision.max_attempts or not transient:
            break
    assert last_error is not None
    raise last_error


async def _invoke_tool(
    tool_fn: Any,
    tool_name: str,
    tool_args: dict[str, Any],
    state: AgentState,
) -> Any:
    import inspect

    if hasattr(tool_fn, "ainvoke"):
        with _trusted_tool_scope(tool_name, state):
            return await tool_fn.ainvoke(tool_args)
    if inspect.iscoroutinefunction(tool_fn):
        with _trusted_tool_scope(tool_name, state):
            return await tool_fn(**tool_args)

    def invoke_sync() -> Any:
        with _trusted_tool_scope(tool_name, state):
            if hasattr(tool_fn, "_run"):
                return tool_fn._run(**tool_args)
            return tool_fn(**tool_args)

    return await asyncio.to_thread(invoke_sync)


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


def _tool_metadata(tool_fn: Any) -> tuple[str, str | None]:
    metadata = getattr(tool_fn, "metadata", None)
    if isinstance(metadata, dict):
        source = str(metadata.get("tool_source") or "builtin")
        server = metadata.get("mcp_server")
        return source, str(server) if server else None
    name = str(getattr(tool_fn, "name", ""))
    return ("minecraft", None) if name.startswith("mc_") else ("builtin", None)


def _tool_invocation(
    tool_call: dict[str, Any],
    *,
    tools_map: dict[str, Any],
    state: AgentState,
) -> ToolInvocation:
    tool_name = str(tool_call.get("name", "unknown"))
    tool_source, mcp_server = _tool_metadata(tools_map.get(tool_name))
    return ToolInvocation(
        tool_call_id=str(tool_call.get("id", "unknown")),
        tool_name=tool_name,
        arguments=dict(tool_call.get("args", {})),
        session_id=str(state.get("session_id", "unknown")),
        conversation_id=state.get("conversation_id"),
        tool_source=tool_source,
        mcp_server=mcp_server,
    )


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


async def _notify_policy_failure(
    observer: ToolInvocationObserver | None,
    invocations: tuple[ToolInvocation, ...],
    code: str,
) -> None:
    if observer is None:
        return
    callback = getattr(observer, "record_policy_failure", None)
    if callback is not None:
        await callback(invocations, code)


async def _notify_approval(
    observer: ToolInvocationObserver | None,
    invocations: tuple[ToolInvocation, ...],
    result: str,
) -> None:
    if observer is None:
        return
    callback = getattr(observer, "record_approval", None)
    if callback is not None:
        await callback(invocations, result)


def _tool_error_code(error: BaseException) -> str:
    if isinstance(error, ToolPolicyError):
        return error.code
    if isinstance(error, TimeoutError):
        return "TOOL_TIMEOUT"
    return "TOOL_ERROR"


def _trusted_tool_scope(tool_name: str, state: AgentState):
    if tool_name not in {"mc_connection", "mc_operate_bot"}:
        return nullcontext()
    from animetta.tools.minecraft.core.tools import bind_minecraft_caller_scope

    identity = state.get("conversation_id") or state.get("session_id", "unknown")
    return bind_minecraft_caller_scope(f"conversation:{identity}")
