"""Credential-free state model for the Bilibili livestream session."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class LivestreamState(StrEnum):
    """Lifecycle states exposed to management clients and OBS pages."""

    STOPPED = "stopped"
    CONNECTING = "connecting"
    PRELIVE = "prelive"
    LIVE = "live"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LivestreamSnapshot:
    """Serializable public state for one process-owned livestream session."""

    state: LivestreamState = LivestreamState.STOPPED
    connected: bool = False
    room_id: int | None = None
    desired_room_id: int | None = None
    retry_count: int = 0
    error_code: str | None = None
    generation_id: int = 0
    message: str = "Stopped"
    updated_at: float = 0.0

    @classmethod
    def initial(cls) -> LivestreamSnapshot:
        """Build the initial stopped snapshot with a current timestamp."""
        return cls(updated_at=time.time())

    def to_dict(self) -> dict[str, Any]:
        """Return the exact credential-free Socket.IO status payload."""
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload
