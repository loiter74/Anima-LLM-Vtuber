"""Bounded conversation policy for model-generated Minecraft missions."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import ValidationError

MINECRAFT_SCHEMA_ERROR_MARKER = "minecraft_mission_schema_error"
MAX_MISSION_ATTEMPTS = 2


def is_mission_call(tool_name: str, tool_args: object) -> bool:
    if tool_name != "mc_execute" or not isinstance(tool_args, dict):
        return False
    request = tool_args.get("request")
    if isinstance(request, dict):
        return request.get("kind") == "mission"
    return tool_args.get("kind") == "mission"


def mission_failure_count(messages: Sequence[BaseMessage]) -> int:
    return sum(
        bool(message.additional_kwargs.get(MINECRAFT_SCHEMA_ERROR_MARKER)) for message in messages
    )


def is_repairable_mission_error(error: Exception) -> bool:
    return isinstance(error, (ValidationError, ValueError))


def mission_problem(
    *,
    error: Exception | None,
    attempt: int,
    exhausted: bool = False,
) -> tuple[str, dict[str, Any]]:
    if exhausted:
        code = "MC_MISSION_REPAIR_EXHAUSTED"
        message = "Minecraft mission validation failed twice; no gameplay was submitted."
        instruction = "Explain the validation failure visibly and ask the user to clarify."
    else:
        code = "MC_MISSION_SCHEMA_INVALID"
        message = str(error or "invalid Minecraft mission")[:2_000]
        instruction = (
            "Correct the complete mission schema once and call mc_execute again."
            if attempt < MAX_MISSION_ATTEMPTS
            else "Do not call mc_execute again; explain the structured error visibly."
        )
    payload = {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "repair_attempt": attempt,
            "repair_remaining": (not exhausted and attempt < MAX_MISSION_ATTEMPTS),
            "instruction": instruction,
            "gameplay_submitted": False,
        },
    }
    kwargs = {
        MINECRAFT_SCHEMA_ERROR_MARKER: not exhausted,
        "minecraft_mission_attempt": attempt,
    }
    return json.dumps(payload, ensure_ascii=False), kwargs
