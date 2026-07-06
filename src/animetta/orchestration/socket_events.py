"""Socket.IO event name constants loaded from config/socket-events.json.

Single source of truth for all Socket.IO event names across the backend.
Import event_name() for normal lookups or EVENTS for direct catalog access.

Example:
    from animetta.orchestration.socket_events import EVENTS

    # In a handler:
    await self.sio.emit(event_name("chat", "sentence"), payload, to=sid)

    # In a graph node:
    await sio.emit(event_name("chat", "transcript"), payload, to=session_id)
"""

import json
from pathlib import Path
from typing import Any

from loguru import logger


def _load_event_names() -> dict[str, Any]:
    """Load event name configuration from config/socket-events.json."""
    # Path: orchestration/socket_events.py -> up 4 dirs -> project root
    config_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "config"
        / "socket-events.json"
    )
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load socket-events.json: {e}, using fallback")
        return {}


EVENTS: dict[str, Any] = _load_event_names()


def event_name(module: str, action: str) -> str:
    """Return a configured Socket.IO event name.

    Raises:
        KeyError: If the event is not declared in config/socket-events.json.
    """
    try:
        name = EVENTS[module][action]["name"]
    except KeyError as exc:
        raise KeyError(
            f"Socket.IO event not configured: {module}.{action}"
        ) from exc

    if not isinstance(name, str) or not name:
        raise KeyError(f"Socket.IO event has no name: {module}.{action}")
    return name
