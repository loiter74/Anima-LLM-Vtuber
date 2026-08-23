"""Stable, privacy-aware projections for the livestream execution console."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from animetta.observability.ports import ObservationQuery

MinecraftActivityReader = Callable[[str], Awaitable[dict[str, Any] | None]]


async def live_overview(
    query: ObservationQuery,
    *,
    limit: int,
    minecraft_activity_reader: MinecraftActivityReader | None = None,
) -> dict[str, Any]:
    bounded_limit = max(1, min(limit, 50))
    summaries = await query.recent_traces(min(100, bounded_limit * 3), 0)
    details: list[Mapping[str, Any]] = []
    active_live_session_id: str | None = None
    for summary in summaries:
        detail = await query.trace_detail(str(summary["trace_id"]))
        if detail is None:
            continue
        attributes = detail.get("attributes") or {}
        live_session_id = (
            str(attributes.get("live_session_id"))
            if isinstance(attributes, Mapping) and attributes.get("live_session_id")
            else None
        )
        if live_session_id and active_live_session_id is None:
            active_live_session_id = live_session_id
        details.append(detail)

    turns: list[dict[str, Any]] = []
    for detail in details:
        attributes = detail.get("attributes") or {}
        if (
            active_live_session_id is None
            or not isinstance(attributes, Mapping)
            or attributes.get("live_session_id") != active_live_session_id
        ):
            continue
        turn = _turn_summary(detail)
        for operation in reversed(turn["_tool_operations"]):
            attrs = operation.get("attributes") or {}
            command_id = attrs.get("minecraft_command_id") if isinstance(attrs, Mapping) else None
            if command_id:
                mc_activity = await _minecraft_activity(
                    minecraft_activity_reader,
                    str(command_id),
                    include_details=False,
                )
                if mc_activity:
                    turn["mc_status"] = str(mc_activity.get("state") or turn["mc_status"])
                break
        turns.append(turn)
        if len(turns) >= bounded_limit:
            break

    tool_operations = [
        operation for turn in turns for operation in turn.pop("_tool_operations", [])
    ]
    successful_tools = sum(item.get("status") == "success" for item in tool_operations)
    mc_operations = [
        item for item in tool_operations if item.get("attributes", {}).get("minecraft_command_id")
    ]
    model_calls = sum(1 for turn in turns for item in turn.pop("_model_operations", []))
    return {
        "api_version": "1",
        "metrics": {
            "turn_count": len(turns),
            "model_calls": model_calls,
            "tool_calls": len(tool_operations),
            "tool_success_rate": (
                round(successful_tools * 100 / len(tool_operations), 1)
                if tool_operations
                else 100.0
            ),
            "mc_command_count": len(mc_operations),
            "mc_status": next(
                (str(turn["mc_status"]) for turn in turns if turn["mc_status"] != "idle"),
                "idle",
            ),
        },
        "turns": turns,
    }


async def live_turn_detail(
    query: ObservationQuery,
    *,
    trace_id: str,
    minecraft_activity_reader: MinecraftActivityReader | None = None,
) -> dict[str, Any] | None:
    detail = await query.trace_detail(trace_id)
    if detail is None:
        return None
    trace_attributes = detail.get("attributes") or {}
    if not isinstance(trace_attributes, Mapping) or not trace_attributes.get("live_session_id"):
        return None
    privacy_mode = str(detail.get("privacy_mode") or "redacted")
    activities: list[dict[str, Any]] = []
    seen_tool = False
    operations = [
        operation for operation in detail.get("operations", ()) if isinstance(operation, Mapping)
    ]
    operation_names = {
        str(operation.get("operation_id")): str(operation.get("name") or "")
        for operation in operations
        if operation.get("operation_id")
    }
    for operation in operations:
        attributes = dict(operation.get("attributes") or {})
        name = str(operation.get("name") or "")
        kind = _activity_kind(name)
        label = _activity_label(name)
        parent_name = operation_names.get(str(operation.get("parent_operation_id")), "")
        if _is_subtitle_translation(operation, name=name, parent_name=parent_name):
            label = "字幕翻译"
        elif kind == "model" and seen_tool and "composer" not in name.lower():
            label = "结合结果复盘"
        activity = {
            "id": operation.get("operation_id"),
            "kind": kind,
            "label": label,
            "name": operation.get("name"),
            "layer": operation.get("layer"),
            "status": operation.get("status") or "running",
            "started_at": operation.get("started_at"),
            "duration_ms": operation.get("duration_ms"),
            "provider": operation.get("provider"),
            "model": operation.get("model"),
            "error": operation.get("error_summary"),
            "attributes": attributes,
        }
        command_id = attributes.get("minecraft_command_id")
        if command_id:
            activity["minecraft"] = await _minecraft_activity(
                minecraft_activity_reader,
                str(command_id),
                include_details=privacy_mode == "full",
            )
        activities.append(activity)
        seen_tool = seen_tool or kind == "tool"

    return {
        "api_version": "1",
        **_public_trace_fields(detail),
        "activities": activities,
        "events": list(detail.get("events") or ()),
    }


def _turn_summary(detail: Mapping[str, Any]) -> dict[str, Any]:
    attributes = dict(detail.get("attributes") or {})
    operations = [item for item in detail.get("operations", ()) if isinstance(item, Mapping)]
    tool_operations = [
        item for item in operations if str(item.get("name") or "").startswith("tool:")
    ]
    model_operations = [
        item
        for item in operations
        if item.get("provider")
        or item.get("model")
        or str(item.get("name") or "").lower().startswith("llm.")
    ]
    return {
        **_public_trace_fields(detail),
        "actor_role": attributes.get("actor_role") or "viewer",
        "source": attributes.get("source") or "chat",
        "live_session_id": attributes.get("live_session_id"),
        "audience": attributes.get("audience"),
        "tool_calls": len(tool_operations),
        "mc_status": _latest_mc_status(tool_operations),
        "_tool_operations": tool_operations,
        "_model_operations": model_operations,
    }


def _public_trace_fields(detail: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": detail.get("trace_id"),
        "message_id": detail.get("message_id"),
        "conversation_id": detail.get("conversation_id"),
        "started_at": detail.get("started_at"),
        "finished_at": detail.get("finished_at"),
        "duration_ms": detail.get("duration_ms"),
        "outcome": detail.get("outcome"),
        "privacy_mode": detail.get("privacy_mode"),
        "content": {
            "user": _content(detail, "user"),
            "assistant": _content(detail, "assistant"),
        },
    }


def _content(detail: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "text": detail.get(f"{prefix}_text"),
        "character_count": detail.get(f"{prefix}_character_count"),
        "byte_count": detail.get(f"{prefix}_byte_count"),
        "digest": detail.get(f"{prefix}_digest"),
    }


def _activity_kind(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith("tool:"):
        return "tool"
    if any(token in lowered for token in ("llm", "reasoner", "composer")):
        return "model"
    if any(token in lowered for token in ("output", "delivery", "tts")):
        return "delivery"
    return "stage"


def _activity_label(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith("tool:"):
        return "决定并调用工具"
    if "composer" in lowered:
        return "组织公开回复"
    if "reasoner" in lowered or "llm" in lowered:
        return "模型规划"
    if "output" in lowered or "delivery" in lowered or "tts" in lowered:
        return "公开投递"
    return name


def _is_subtitle_translation(
    operation: Mapping[str, Any],
    *,
    name: str,
    parent_name: str,
) -> bool:
    return (
        name.lower() == "llm.chat_messages"
        and operation.get("critical_path") is False
        and _activity_kind(parent_name) == "delivery"
    )


def _latest_mc_status(operations: Sequence[Mapping[str, Any]]) -> str:
    for operation in reversed(operations):
        attrs = operation.get("attributes") or {}
        if isinstance(attrs, Mapping) and attrs.get("minecraft_command_id"):
            return str(operation.get("status") or "running")
    return "idle"


async def _minecraft_activity(
    reader: MinecraftActivityReader | None,
    command_id: str,
    *,
    include_details: bool,
) -> dict[str, Any] | None:
    if reader is None:
        return None
    activity = await reader(command_id)
    if activity is None:
        return None
    if include_details:
        return activity
    return {
        "command_id": "[REDACTED]",
        "state": activity.get("state"),
        "failure_reason": activity.get("failure_reason"),
        "transitions": [
            {
                "from_state": item.get("from_state"),
                "to_state": item.get("to_state"),
                "reason_code": item.get("reason_code"),
                "occurred_at_ms": item.get("occurred_at_ms"),
            }
            for item in activity.get("transitions", ())
        ],
    }
