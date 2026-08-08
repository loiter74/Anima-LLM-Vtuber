"""Protocol and additive stores for world facts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Protocol

from .models import (
    AcquisitionEvidence,
    DiscoveryObservation,
    ObservedFact,
    WorldFact,
    WorldFactIdentity,
    WorldFactState,
)


class WorldFactStore(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def upsert_observed(
        self,
        identity: WorldFactIdentity,
        fact: ObservedFact,
        observation: DiscoveryObservation,
    ) -> tuple[WorldFact, bool]: ...

    async def mark_acquired(self, evidence: AcquisitionEvidence) -> WorldFact: ...

    async def get(self, fact_id: str) -> WorldFact | None: ...

    async def list_scope(
        self,
        *,
        world_identity_hash: str,
        environment_fingerprint: str,
        state: WorldFactState | None = None,
    ) -> tuple[WorldFact, ...]: ...


def _new_world_fact(
    identity: WorldFactIdentity,
    fact: ObservedFact,
    observation: DiscoveryObservation,
) -> WorldFact:
    observation_ref = f"observation:{observation.observation_id}"
    return WorldFact(
        fact_id=identity.fact_id,
        runtime_instance_id=observation.runtime_instance_id,
        identity=identity,
        state=WorldFactState.OBSERVED,
        first_observation_ref=observation_ref,
        first_observation_hash=observation.observation_hash,
        last_observation_ref=observation_ref,
        last_observation_hash=observation.observation_hash,
        first_seen_at_ms=observation.captured_at_ms,
        last_seen_at_ms=observation.captured_at_ms,
        first_seen_tick=observation.tick,
        last_seen_tick=observation.tick,
        observation_count=1,
        coarse_location=fact.coarse_location,
        metadata=fact.metadata,
    )


def _acquired(fact: WorldFact, evidence: AcquisitionEvidence) -> WorldFact:
    if (
        not evidence.committed
        or evidence.fallback_only
        or not evidence.explained_inventory_delta
        or evidence.inventory_delta <= 0
    ):
        raise ValueError("ACQUISITION_EVIDENCE_INELIGIBLE")
    if (
        evidence.world_identity_hash != fact.identity.world_identity_hash
        or evidence.environment_fingerprint != fact.identity.environment_fingerprint
    ):
        raise ValueError("ACQUISITION_WORLD_MISMATCH")
    if evidence.runtime_instance_id != fact.runtime_instance_id:
        raise ValueError("ACQUISITION_RUNTIME_MISMATCH")
    if evidence.observed_at_ms < fact.last_seen_at_ms:
        raise ValueError("STALE_DISCOVERY_EVIDENCE")
    return fact.model_copy(
        update={
            "state": WorldFactState.ACQUIRED,
            "acquisition_command_ref": f"command:{evidence.command_id}",
            "acquisition_receipt_ref": f"receipt:{evidence.receipt_id}",
            "acquisition_observation_ref": f"observation:{evidence.after_observation_id}",
        }
    )


class InMemoryWorldFactStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._facts: dict[str, WorldFact] = {}
        self._evidence_refs: dict[str, set[str]] = {}

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def upsert_observed(
        self,
        identity: WorldFactIdentity,
        fact: ObservedFact,
        observation: DiscoveryObservation,
    ) -> tuple[WorldFact, bool]:
        async with self._lock:
            existing = self._facts.get(identity.fact_id)
            evidence_ref = f"observation:{observation.observation_id}"
            if existing is None:
                created = _new_world_fact(identity, fact, observation)
                self._facts[identity.fact_id] = created
                self._evidence_refs[identity.fact_id] = {evidence_ref}
                return created.model_copy(deep=True), True
            refs = self._evidence_refs[identity.fact_id]
            if evidence_ref in refs:
                return existing.model_copy(deep=True), False
            refs.add(evidence_ref)
            updated = existing.model_copy(
                update={
                    "last_observation_ref": evidence_ref,
                    "last_observation_hash": observation.observation_hash,
                    "last_seen_at_ms": observation.captured_at_ms,
                    "last_seen_tick": observation.tick,
                    "observation_count": existing.observation_count + 1,
                    "coarse_location": fact.coarse_location or existing.coarse_location,
                    "metadata": fact.metadata or existing.metadata,
                }
            )
            self._facts[identity.fact_id] = updated
            return updated.model_copy(deep=True), False

    async def mark_acquired(self, evidence: AcquisitionEvidence) -> WorldFact:
        async with self._lock:
            current = self._facts[evidence.fact_id]
            updated = _acquired(current, evidence)
            self._facts[evidence.fact_id] = updated
            self._evidence_refs[evidence.fact_id].add(f"receipt:{evidence.receipt_id}")
            return updated.model_copy(deep=True)

    async def get(self, fact_id: str) -> WorldFact | None:
        fact = self._facts.get(fact_id)
        return fact.model_copy(deep=True) if fact else None

    async def list_scope(
        self,
        *,
        world_identity_hash: str,
        environment_fingerprint: str,
        state: WorldFactState | None = None,
    ) -> tuple[WorldFact, ...]:
        return tuple(
            fact.model_copy(deep=True)
            for fact in sorted(self._facts.values(), key=lambda item: item.fact_id)
            if fact.identity.world_identity_hash == world_identity_hash
            and fact.identity.environment_fingerprint == environment_fingerprint
            and (state is None or fact.state is state)
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS world_facts (
  fact_id TEXT PRIMARY KEY,
  runtime_instance_id TEXT NOT NULL,
  world_identity_hash TEXT NOT NULL,
  environment_fingerprint TEXT NOT NULL,
  fact_kind TEXT NOT NULL,
  fact_key TEXT NOT NULL,
  state TEXT NOT NULL,
  first_observation_ref TEXT NOT NULL,
  first_observation_hash TEXT NOT NULL,
  last_observation_ref TEXT NOT NULL,
  last_observation_hash TEXT NOT NULL,
  first_seen_at_ms INTEGER NOT NULL,
  last_seen_at_ms INTEGER NOT NULL,
  first_seen_tick INTEGER NOT NULL,
  last_seen_tick INTEGER NOT NULL,
  observation_count INTEGER NOT NULL,
  coarse_location TEXT,
  metadata_json TEXT NOT NULL,
  acquisition_command_ref TEXT,
  acquisition_receipt_ref TEXT,
  acquisition_observation_ref TEXT,
  UNIQUE(world_identity_hash,environment_fingerprint,fact_kind,fact_key)
);
CREATE TABLE IF NOT EXISTS world_fact_evidence (
  evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
  fact_id TEXT NOT NULL REFERENCES world_facts(fact_id),
  evidence_kind TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  occurred_at_ms INTEGER NOT NULL,
  UNIQUE(fact_id,evidence_ref)
);
CREATE INDEX IF NOT EXISTS idx_world_facts_scope_kind
ON world_facts(world_identity_hash,environment_fingerprint,fact_kind,state);
"""


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SQLiteWorldFactStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: Any = None
        self._lock = asyncio.Lock()

    def _require_db(self) -> Any:
        if self._db is None:
            raise RuntimeError("world fact store is not connected")
        return self._db

    async def connect(self) -> None:
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @staticmethod
    def _row(row: Any) -> WorldFact:
        return WorldFact(
            fact_id=row["fact_id"],
            runtime_instance_id=row["runtime_instance_id"],
            identity=WorldFactIdentity(
                world_identity_hash=row["world_identity_hash"],
                environment_fingerprint=row["environment_fingerprint"],
                fact_kind=row["fact_kind"],
                fact_key=row["fact_key"],
            ),
            state=WorldFactState(row["state"]),
            first_observation_ref=row["first_observation_ref"],
            first_observation_hash=row["first_observation_hash"],
            last_observation_ref=row["last_observation_ref"],
            last_observation_hash=row["last_observation_hash"],
            first_seen_at_ms=row["first_seen_at_ms"],
            last_seen_at_ms=row["last_seen_at_ms"],
            first_seen_tick=row["first_seen_tick"],
            last_seen_tick=row["last_seen_tick"],
            observation_count=row["observation_count"],
            coarse_location=row["coarse_location"],
            metadata=json.loads(row["metadata_json"]),
            acquisition_command_ref=row["acquisition_command_ref"],
            acquisition_receipt_ref=row["acquisition_receipt_ref"],
            acquisition_observation_ref=row["acquisition_observation_ref"],
        )

    async def get(self, fact_id: str) -> WorldFact | None:
        cursor = await self._require_db().execute(
            "SELECT * FROM world_facts WHERE fact_id=?", (fact_id,)
        )
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def list_scope(
        self,
        *,
        world_identity_hash: str,
        environment_fingerprint: str,
        state: WorldFactState | None = None,
    ) -> tuple[WorldFact, ...]:
        query = (
            "SELECT * FROM world_facts WHERE world_identity_hash=? AND environment_fingerprint=?"
        )
        values: list[str] = [world_identity_hash, environment_fingerprint]
        if state is not None:
            query += " AND state=?"
            values.append(state.value)
        query += " ORDER BY fact_id"
        cursor = await self._require_db().execute(query, tuple(values))
        return tuple(self._row(row) for row in await cursor.fetchall())

    async def upsert_observed(
        self,
        identity: WorldFactIdentity,
        fact: ObservedFact,
        observation: DiscoveryObservation,
    ) -> tuple[WorldFact, bool]:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing = await self.get(identity.fact_id)
                evidence_ref = f"observation:{observation.observation_id}"
                if existing is None:
                    result = _new_world_fact(identity, fact, observation)
                    values = result.model_dump(mode="json")
                    await db.execute(
                        """INSERT INTO world_facts VALUES
                        (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            result.fact_id,
                            result.runtime_instance_id,
                            identity.world_identity_hash,
                            identity.environment_fingerprint,
                            identity.fact_kind,
                            identity.fact_key,
                            result.state.value,
                            result.first_observation_ref,
                            result.first_observation_hash,
                            result.last_observation_ref,
                            result.last_observation_hash,
                            result.first_seen_at_ms,
                            result.last_seen_at_ms,
                            result.first_seen_tick,
                            result.last_seen_tick,
                            result.observation_count,
                            result.coarse_location,
                            _dump(values["metadata"]),
                            None,
                            None,
                            None,
                        ),
                    )
                    is_new = True
                else:
                    evidence_cursor = await db.execute(
                        """SELECT 1 FROM world_fact_evidence
                        WHERE fact_id=? AND evidence_ref=?""",
                        (identity.fact_id, evidence_ref),
                    )
                    if await evidence_cursor.fetchone():
                        await db.commit()
                        return existing, False
                    result = existing.model_copy(
                        update={
                            "last_observation_ref": evidence_ref,
                            "last_observation_hash": observation.observation_hash,
                            "last_seen_at_ms": observation.captured_at_ms,
                            "last_seen_tick": observation.tick,
                            "observation_count": existing.observation_count + 1,
                            "coarse_location": fact.coarse_location or existing.coarse_location,
                            "metadata": fact.metadata or existing.metadata,
                        }
                    )
                    await db.execute(
                        """UPDATE world_facts SET last_observation_ref=?,
                        last_observation_hash=?,last_seen_at_ms=?,last_seen_tick=?,
                        observation_count=?,coarse_location=?,metadata_json=? WHERE fact_id=?""",
                        (
                            result.last_observation_ref,
                            result.last_observation_hash,
                            result.last_seen_at_ms,
                            result.last_seen_tick,
                            result.observation_count,
                            result.coarse_location,
                            _dump(result.metadata),
                            result.fact_id,
                        ),
                    )
                    is_new = False
                await db.execute(
                    """INSERT INTO world_fact_evidence
                    (fact_id,evidence_kind,evidence_ref,payload_json,occurred_at_ms)
                    VALUES (?,'observation',?,?,?)""",
                    (
                        identity.fact_id,
                        evidence_ref,
                        _dump(observation.model_dump(mode="json")),
                        observation.captured_at_ms,
                    ),
                )
                await db.commit()
                return result, is_new
            except Exception:
                await db.rollback()
                raise

    async def mark_acquired(self, evidence: AcquisitionEvidence) -> WorldFact:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                current = await self.get(evidence.fact_id)
                if current is None:
                    raise KeyError(evidence.fact_id)
                result = _acquired(current, evidence)
                await db.execute(
                    """UPDATE world_facts SET state='acquired',acquisition_command_ref=?,
                    acquisition_receipt_ref=?,acquisition_observation_ref=? WHERE fact_id=?""",
                    (
                        result.acquisition_command_ref,
                        result.acquisition_receipt_ref,
                        result.acquisition_observation_ref,
                        result.fact_id,
                    ),
                )
                await db.execute(
                    """INSERT OR IGNORE INTO world_fact_evidence
                    (fact_id,evidence_kind,evidence_ref,payload_json,occurred_at_ms)
                    VALUES (?,'acquisition',?,?,?)""",
                    (
                        result.fact_id,
                        f"receipt:{evidence.receipt_id}",
                        _dump(evidence.model_dump(mode="json")),
                        evidence.observed_at_ms,
                    ),
                )
                await db.commit()
                return result
            except Exception:
                await db.rollback()
                raise
