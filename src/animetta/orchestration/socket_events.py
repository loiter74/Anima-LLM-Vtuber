"""Socket.IO event name constants loaded from config/socket-events.json.

Single source of truth for all Socket.IO event names across the backend.
Import EVENTS and reference as EVENTS[<module>][<event>]["name"].

Example:
    from animetta.orchestration.socket_events import EVENTS

    # In a handler:
    await self.sio.emit(EVENTS["chat"]["sentence"]["name"], payload, to=sid)

    # In a graph node:
    await sio.emit(EVENTS["chat"]["transcript"]["name"], payload, to=session_id)
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
