"""Load the shared Socket.IO event catalog without transport dependencies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


def load_socket_event_catalog() -> dict[str, Any]:
    """Load the repository's canonical event catalog, or an empty safe fallback."""
    config_path = Path(__file__).resolve().parents[2] / "config" / "socket-events.json"
    try:
        with config_path.open(encoding="utf-8") as stream:
            catalog = json.load(stream)
    except Exception as exc:
        logger.warning(
            "Failed to load socket-events.json: {}, using fallback",
            type(exc).__name__,
        )
        return {}
    return catalog if isinstance(catalog, dict) else {}


EVENTS: dict[str, Any] = load_socket_event_catalog()

__all__ = ["EVENTS", "load_socket_event_catalog"]
