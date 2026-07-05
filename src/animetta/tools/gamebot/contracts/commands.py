"""Gamebot command and response contracts — transport-independent schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


def seconds_to_ms(seconds: float | int) -> int:
    """Convert seconds to milliseconds. Raises ValueError for negative values."""
    if seconds < 0:
        raise ValueError(f"timeout cannot be negative: {seconds}")
    return int(seconds * 1000)


class GameBotCommandRequest(BaseModel):
    """A command to send to a game bot runtime.

    Transport-independent: serialization format is determined by the transport layer.
    Timeout is always in milliseconds for contract stability.
    """

    id: int
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = 60000


class GameBotCommandResponse(BaseModel):
    """A response from a game bot runtime.

    Status is constrained to the three values used by the JSON-line protocol:
    - "success": command completed, result contains output
    - "error": command failed, result contains error message
    - "event": async event, id is None, result contains event payload
    """

    id: int | None
    status: Literal["success", "error", "event"]
    result: Any = None
