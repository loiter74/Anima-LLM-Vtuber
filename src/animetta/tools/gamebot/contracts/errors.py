"""Gamebot error contracts — timeout, process-exit, and compatibility helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GameBotError:
    """A structured error from a game bot runtime interaction."""

    action: str
    kind: str
    message: str


def make_timeout_error(action: str, timeout_seconds: float) -> GameBotError:
    return GameBotError(
        action=action,
        kind="timeout",
        message=f"Action '{action}' timed out after {timeout_seconds}s",
    )


def make_process_exit_error(action: str, returncode: int) -> GameBotError:
    return GameBotError(
        action=action,
        kind="process_exit",
        message=f"Action '{action}' failed: process exited with code {returncode}",
    )


def to_bridge_response(error: GameBotError) -> dict[str, Any]:
    """Convert a GameBotError to the bridge-style response dict.

    Preserves the existing `{"status": "error", "result": "<message>"}`
    shape expected by all current GameBot transport callers.
    """
    return {"status": "error", "result": error.message}
