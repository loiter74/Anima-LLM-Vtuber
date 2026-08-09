"""Stable request identity for livestream memory operations."""

from __future__ import annotations

from dataclasses import dataclass


def normalize_actor_id(actor_id: object, channel: str | None) -> str | None:
    """Namespace an external identity so providers can never cross-talk."""
    raw = str(actor_id).strip() if actor_id is not None else ""
    if not raw or raw == "0":
        return None
    if ":" in raw:
        return raw
    namespace = (channel or "local").strip().lower()
    if namespace in {"web", "desktop", "electron"}:
        namespace = "local"
    if namespace == "local" and raw == "user":
        return "local:owner"
    return f"{namespace}:{raw}"


@dataclass(frozen=True, slots=True)
class MemoryContext:
    """Identity used for memory visibility, attribution, and provenance.

    ``connection_id`` is deliberately trace-only. It may contain an ephemeral
    Socket.IO sid but is never returned as a visibility key.
    """

    actor_id: str | None = None
    conversation_id: str | None = None
    stream_id: str | None = None
    persona_id: str | None = None
    channel: str = "unknown"
    connection_id: str | None = None
    actor_role: str | None = None
    source: str | None = None
    live_session_id: str | None = None
    message_id: str | None = None
    task_id: str | None = None
    turn_id: str | None = None
    audience: str | None = None

    def visibility_keys(self) -> dict[str, str]:
        """Return stable keys that may participate in visibility policy."""

        keys: dict[str, str] = {}
        if self.actor_id:
            keys["actor_id"] = self.actor_id
        if self.stream_id:
            keys["stream_id"] = self.stream_id
        return keys

    def to_origin(self) -> dict[str, str]:
        """Serialize available provenance, including trace-only connection ID."""

        values = {
            "actor_id": self.actor_id,
            "conversation_id": self.conversation_id,
            "stream_id": self.stream_id,
            "persona_id": self.persona_id,
            "channel": self.channel,
            "connection_id": self.connection_id,
            "actor_role": self.actor_role,
            "source": self.source,
            "live_session_id": self.live_session_id,
            "message_id": self.message_id,
            "task_id": self.task_id,
            "turn_id": self.turn_id,
            "audience": self.audience,
        }
        return {key: value for key, value in values.items() if value}
