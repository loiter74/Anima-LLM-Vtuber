"""Gamebot event contracts — async runtime notification schemas."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# All event types emitted by the current JSON-line protocol.
KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "login",
        "spawn",
        "heartbeat",
        "disconnect",
        "initial_loadout",
        "viewer_joined",
        "viewer_left",
        "client_viewer_status",
    }
)


@dataclass
class GameBotEvent:
    """An asynchronous event from a game bot runtime.

    Unknown event types are preserved as-is for forward compatibility.
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)


def parse_event_from_response_line(line: str) -> GameBotEvent | None:
    """Parse a JSON-line response into a GameBotEvent if it is an event message.

    Returns None for non-event responses, malformed JSON, or missing type field.
    Does not raise — safe for use in the stdout reader loop.
    """
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None

    if data.get("status") != "event":
        return None
    if data.get("id") is not None:
        return None

    result = data.get("result")
    if not isinstance(result, dict):
        return None

    event_type = result.get("type")
    if not event_type:
        return None

    # Extract payload — everything in result except 'type'
    payload = {k: v for k, v in result.items() if k != "type"}
    return GameBotEvent(type=event_type, payload=payload)
