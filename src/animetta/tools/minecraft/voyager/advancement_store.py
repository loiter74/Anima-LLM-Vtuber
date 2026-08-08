"""Durable vanilla advancement event ledger."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from animetta.tools.gamebot.contracts.v2 import (
    AdvancementObservedEvent,
    canonical_json_hash,
)


def _valid_hash(event: AdvancementObservedEvent) -> bool:
    return event.content_hash == canonical_json_hash(
        event.model_dump(mode="json", exclude={"content_hash"})
    )


def _active(events: tuple[AdvancementObservedEvent, ...]) -> frozenset[str]:
    state: dict[str, str] = {}
    for event in events:
        state[event.advancement_id] = event.action
    return frozenset(key for key, action in state.items() if action == "add")


class AdvancementEventStore(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def append(self, event: AdvancementObservedEvent) -> bool: ...

    async def list_scope(
        self,
        *,
        world_identity_hash: str,
        runtime_instance_id: str,
    ) -> tuple[AdvancementObservedEvent, ...]: ...

    async def active_added(
        self,
        *,
        world_identity_hash: str,
        runtime_instance_id: str,
    ) -> frozenset[str]: ...


class InMemoryAdvancementEventStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._events: dict[str, AdvancementObservedEvent] = {}

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def append(self, event: AdvancementObservedEvent) -> bool:
        if not _valid_hash(event):
            raise ValueError("ADVANCEMENT_EVENT_HASH_MISMATCH")
        async with self._lock:
            if event.content_hash in self._events:
                return False
            self._events[event.content_hash] = event
            return True

    async def list_scope(
        self,
        *,
        world_identity_hash: str,
        runtime_instance_id: str,
    ) -> tuple[AdvancementObservedEvent, ...]:
        return tuple(
            sorted(
                (
                    event.model_copy(deep=True)
                    for event in self._events.values()
                    if event.world_identity.world_identity_hash == world_identity_hash
                    and event.runtime_instance_id == runtime_instance_id
                ),
                key=lambda event: (event.observed_at_ms, event.tick, event.event_id),
            )
        )

    async def active_added(self, **scope: str) -> frozenset[str]:
        return _active(await self.list_scope(**scope))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS advancement_events (
  content_hash TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  runtime_instance_id TEXT NOT NULL,
  world_identity_hash TEXT NOT NULL,
  advancement_id TEXT NOT NULL,
  action TEXT NOT NULL,
  observed_at_ms INTEGER NOT NULL,
  tick INTEGER NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_advancement_events_scope
ON advancement_events(world_identity_hash,runtime_instance_id,observed_at_ms,tick,event_id);
"""


class SQLiteAdvancementEventStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: Any = None
        self._lock = asyncio.Lock()

    def _require_db(self) -> Any:
        if self._db is None:
            raise RuntimeError("advancement event store is not connected")
        return self._db

    async def connect(self) -> None:
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def append(self, event: AdvancementObservedEvent) -> bool:
        if not _valid_hash(event):
            raise ValueError("ADVANCEMENT_EVENT_HASH_MISMATCH")
        payload = json.dumps(
            event.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        async with self._lock:
            cursor = await self._require_db().execute(
                """INSERT OR IGNORE INTO advancement_events VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    event.content_hash,
                    event.event_id,
                    event.runtime_instance_id,
                    event.world_identity.world_identity_hash,
                    event.advancement_id,
                    event.action,
                    event.observed_at_ms,
                    event.tick,
                    payload,
                ),
            )
            await self._require_db().commit()
            return cursor.rowcount == 1

    async def list_scope(
        self,
        *,
        world_identity_hash: str,
        runtime_instance_id: str,
    ) -> tuple[AdvancementObservedEvent, ...]:
        cursor = await self._require_db().execute(
            """SELECT payload_json FROM advancement_events
            WHERE world_identity_hash=? AND runtime_instance_id=?
            ORDER BY observed_at_ms,tick,event_id""",
            (world_identity_hash, runtime_instance_id),
        )
        return tuple(
            AdvancementObservedEvent.model_validate(json.loads(row[0]))
            for row in await cursor.fetchall()
        )

    async def active_added(self, **scope: str) -> frozenset[str]:
        return _active(await self.list_scope(**scope))


class AdvancementEventRecorder:
    """Validate asynchronous bridge events and commit them to one ledger."""

    def __init__(self, *, bridge: Any, store: AdvancementEventStore) -> None:
        self._bridge = bridge
        self._store = store
        self._tasks: set[asyncio.Task[bool]] = set()
        self.invalid_events = 0

    def start(self) -> None:
        self._bridge.add_runtime_event_callback(self._on_event)

    def _on_event(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "advancement_observed":
            return
        try:
            event = AdvancementObservedEvent.model_validate(
                {key: value for key, value in payload.items() if key != "type"}
            )
        except ValidationError:
            self.invalid_events += 1
            return
        task = asyncio.get_running_loop().create_task(self._store.append(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        while self._tasks:
            tasks = tuple(self._tasks)
            await asyncio.gather(*tasks)
