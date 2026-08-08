"""Best-effort at-least-once lifecycle publication with transition-ID deduplication."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .journal import CommandJournal


class TransitionEventPublisher:
    def __init__(
        self,
        *,
        repository: CommandJournal,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        maximum_events_per_publish: int = 100,
        maximum_delivered_ids: int = 10_000,
    ) -> None:
        self._repository = repository
        self._emit = emit
        self._maximum_events_per_publish = maximum_events_per_publish
        self._maximum_delivered_ids = maximum_delivered_ids
        self._delivered: dict[str, None] = {}

    async def publish_command(self, command_id: str) -> int:
        published = 0
        for transition in await self._repository.transitions(command_id):
            event_id = str(transition.transition_id)
            if event_id in self._delivered:
                continue
            if published >= self._maximum_events_per_publish:
                break
            event = {
                "event": "minecraft.command.transition",
                "event_id": str(transition.transition_id),
                "transition_id": str(transition.transition_id),
                "command_id": transition.command_id,
                "from_state": transition.from_state,
                "to_state": transition.to_state,
                "reason_code": transition.reason_code,
                "occurred_at_ms": transition.occurred_at_ms,
            }
            try:
                await self._emit(event)
            except Exception:
                continue
            self._delivered[event_id] = None
            while len(self._delivered) > self._maximum_delivered_ids:
                self._delivered.pop(next(iter(self._delivered)))
            published += 1
        return published


class TransitionEventConsumer:
    def __init__(self, *, maximum_ids: int = 10_000) -> None:
        self._maximum_ids = maximum_ids
        self._seen: dict[str, None] = {}

    def accept(self, event: dict) -> bool:
        event_id = str(event["event_id"])
        if event_id in self._seen:
            return False
        self._seen[event_id] = None
        while len(self._seen) > self._maximum_ids:
            self._seen.pop(next(iter(self._seen)))
        return True
