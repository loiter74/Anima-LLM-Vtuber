"""SQLite implementation of the authoritative Voyager command journal."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash

from .command_models import TERMINAL_COMMAND_STATES, CommandState, validate_transition
from .journal import (
    CommandDraft,
    CommandTransition,
    IdempotencyConflictError,
    JournalCommand,
    ProjectionPage,
    QueueCapacityExceededError,
    StaleCommandVersionError,
    StartupRecovery,
    StepRecord,
    StopBarrierCommit,
)
from .public_activity import ActivityDraft, ActivityRecord, ActivityRecordPage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_schema_meta (
  schema_version INTEGER PRIMARY KEY,
  applied_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS controller_state (
  singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
  state TEXT NOT NULL,
  state_version INTEGER NOT NULL,
  active_command_id TEXT,
  stop_barrier_id TEXT,
  accepting_execute INTEGER NOT NULL,
  runtime_instance_id TEXT,
  manifest_digest TEXT,
  projection_version INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
  queue_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  command_id TEXT NOT NULL UNIQUE,
  caller_scope TEXT NOT NULL,
  request_id TEXT NOT NULL,
  request_hash TEXT NOT NULL CHECK(length(request_hash) = 64),
  kind TEXT NOT NULL CHECK(kind IN ('execute', 'stop')),
  mode TEXT,
  contract_version TEXT NOT NULL DEFAULT '1',
  payload_json TEXT NOT NULL,
  requested_budget_json TEXT NOT NULL,
  effective_budget_json TEXT NOT NULL,
  state TEXT NOT NULL,
  state_version INTEGER NOT NULL,
  accepted_at_ms INTEGER NOT NULL,
  queue_deadline_ms INTEGER,
  started_at_ms INTEGER,
  execution_deadline_ms INTEGER,
  cancel_requested_at_ms INTEGER,
  active_step_id TEXT,
  runtime_instance_id TEXT,
  blocked_reason_code TEXT,
  terminal_at_ms INTEGER,
  terminal_result_json TEXT,
  UNIQUE (caller_scope, request_id)
);
CREATE TABLE IF NOT EXISTS command_transitions (
  transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
  command_id TEXT NOT NULL REFERENCES commands(command_id),
  from_state TEXT,
  to_state TEXT NOT NULL,
  command_version INTEGER NOT NULL,
  reason_code TEXT NOT NULL,
  actor TEXT NOT NULL,
  details_json TEXT NOT NULL,
  occurred_at_ms INTEGER NOT NULL,
  UNIQUE (command_id, command_version)
);
CREATE TABLE IF NOT EXISTS command_steps (
  step_id TEXT PRIMARY KEY,
  command_id TEXT NOT NULL REFERENCES commands(command_id),
  ordinal INTEGER NOT NULL,
  strategy_state_hash TEXT NOT NULL,
  capability TEXT NOT NULL,
  params_hash TEXT NOT NULL,
  params_json TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  runtime_instance_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('reserved','dispatched','settled','unknown')),
  reservation_json TEXT NOT NULL,
  before_observation_hash TEXT NOT NULL,
  receipt_id TEXT,
  created_at_ms INTEGER NOT NULL,
  settled_at_ms INTEGER,
  UNIQUE (command_id, ordinal),
  UNIQUE (runtime_instance_id, correlation_id)
);
CREATE TABLE IF NOT EXISTS action_receipts (
  receipt_id TEXT PRIMARY KEY,
  command_id TEXT NOT NULL REFERENCES commands(command_id),
  step_id TEXT,
  ordinal INTEGER NOT NULL,
  runtime_instance_id TEXT,
  correlation_id TEXT,
  previous_receipt_hash TEXT NOT NULL DEFAULT '',
  content_hash TEXT UNIQUE,
  outcome TEXT,
  before_observation_hash TEXT,
  after_observation_hash TEXT,
  mutations_json TEXT NOT NULL DEFAULT '[]',
  budget_delta_json TEXT NOT NULL DEFAULT '{}',
  receipt_json TEXT NOT NULL,
  persisted_at_ms INTEGER NOT NULL DEFAULT 0,
  UNIQUE (command_id, ordinal)
);
CREATE TABLE IF NOT EXISTS command_budget_usage (
  command_id TEXT PRIMARY KEY REFERENCES commands(command_id),
  usage_version INTEGER NOT NULL,
  settled_usage_json TEXT NOT NULL,
  reserved_usage_json TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS recovery_attempts (
  recovery_id TEXT PRIMARY KEY,
  command_id TEXT NOT NULL REFERENCES commands(command_id),
  recovery_json TEXT NOT NULL,
  completed_at_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS checkpoints (
  checkpoint_id TEXT PRIMARY KEY,
  command_id TEXT NOT NULL REFERENCES commands(command_id),
  checkpoint_json TEXT NOT NULL,
  committed_at_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS idempotency_tombstones (
  caller_scope TEXT NOT NULL,
  request_id TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  command_id TEXT NOT NULL,
  terminal_state TEXT,
  terminal_result_hash TEXT,
  created_at_ms INTEGER NOT NULL,
  PRIMARY KEY (caller_scope, request_id)
);
CREATE TABLE IF NOT EXISTS public_activity_events (
  activity_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  source_key TEXT NOT NULL UNIQUE,
  command_id TEXT NOT NULL REFERENCES commands(command_id),
  caller_scope TEXT NOT NULL,
  mission_id TEXT,
  payload_json TEXT NOT NULL,
  occurred_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commands_state_sequence
ON commands(state, queue_sequence);
CREATE INDEX IF NOT EXISTS idx_commands_queue_deadline
ON commands(state, queue_deadline_ms);
CREATE INDEX IF NOT EXISTS idx_commands_terminal_at
ON commands(terminal_at_ms);
CREATE INDEX IF NOT EXISTS idx_transitions_command_id
ON command_transitions(command_id, transition_id);
CREATE INDEX IF NOT EXISTS idx_receipts_command_ordinal
ON action_receipts(command_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_recovery_command
ON recovery_attempts(command_id, completed_at_ms);
CREATE INDEX IF NOT EXISTS idx_activity_scope_sequence
ON public_activity_events(caller_scope, activity_sequence);
CREATE INDEX IF NOT EXISTS idx_activity_command_sequence
ON public_activity_events(command_id, activity_sequence);
CREATE INDEX IF NOT EXISTS idx_activity_occurred_at
ON public_activity_events(occurred_at_ms);
"""


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SQLiteCommandJournal:
    SCHEMA_VERSION = 2

    def __init__(self, db_path: str | Path, *, queue_capacity: int = 100) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be positive")
        self._db_path = str(db_path)
        self._queue_capacity = queue_capacity
        self._db: Any = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(_SCHEMA)
        await self._db.execute(
            "INSERT OR IGNORE INTO journal_schema_meta VALUES (?, ?)",
            (self.SCHEMA_VERSION, 0),
        )
        await self._db.execute(
            """INSERT OR IGNORE INTO controller_state
            (singleton_id,state,state_version,accepting_execute,projection_version,updated_at_ms)
            VALUES (1,'idle',0,1,0,0)"""
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def begin_shutdown(self, *, occurred_at_ms: int) -> None:
        await self._require_db().execute(
            """UPDATE controller_state SET state='stopping',accepting_execute=0,
            projection_version=projection_version+1,updated_at_ms=? WHERE singleton_id=1""",
            (occurred_at_ms,),
        )
        await self._require_db().commit()

    async def begin_session(self, *, occurred_at_ms: int) -> None:
        db = self._require_db()
        blocked = await db.execute("SELECT 1 FROM commands WHERE state='blocked_unknown' LIMIT 1")
        if await blocked.fetchone():
            raise RuntimeError("CONTROLLER_QUARANTINED")
        await db.execute(
            """UPDATE controller_state SET state='idle',accepting_execute=1,
            stop_barrier_id=NULL,projection_version=projection_version+1,updated_at_ms=?
            WHERE singleton_id=1 AND accepting_execute=0""",
            (occurred_at_ms,),
        )
        await db.commit()

    def _require_db(self) -> Any:
        if self._db is None:
            raise RuntimeError("journal is not connected")
        return self._db

    @staticmethod
    def _row_to_command(row: Any) -> JournalCommand:
        return JournalCommand(
            command_id=row["command_id"],
            caller_scope=row["caller_scope"],
            request_id=row["request_id"],
            request_hash=row["request_hash"],
            kind=row["kind"],
            mode=row["mode"],
            payload=json.loads(row["payload_json"]),
            requested_budget=json.loads(row["requested_budget_json"]),
            effective_budget=json.loads(row["effective_budget_json"]),
            accepted_at_ms=row["accepted_at_ms"],
            queue_deadline_ms=row["queue_deadline_ms"],
            execution_deadline_ms=row["execution_deadline_ms"],
            queue_sequence=row["queue_sequence"],
            state=CommandState(row["state"]),
            state_version=row["state_version"],
            started_at_ms=row["started_at_ms"],
            cancel_requested_at_ms=row["cancel_requested_at_ms"],
            active_step_id=row["active_step_id"],
            runtime_instance_id=row["runtime_instance_id"],
            blocked_reason_code=row["blocked_reason_code"],
            terminal_at_ms=row["terminal_at_ms"],
            terminal_result=json.loads(row["terminal_result_json"])
            if row["terminal_result_json"]
            else None,
        )

    async def _fetch_command(self, command_id: str) -> JournalCommand | None:
        cursor = await self._require_db().execute(
            "SELECT * FROM commands WHERE command_id=?", (command_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_command(row) if row else None

    async def create_command(self, draft: CommandDraft) -> tuple[JournalCommand, bool]:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """SELECT request_hash, command_id FROM idempotency_tombstones
                    WHERE caller_scope=? AND request_id=?""",
                    (draft.caller_scope, draft.request_id),
                )
                tombstone = await cursor.fetchone()
                if tombstone:
                    if tombstone["request_hash"] != draft.request_hash:
                        raise IdempotencyConflictError("IDEMPOTENCY_CONFLICT")
                    command = await self._fetch_command(tombstone["command_id"])
                    if command is None:
                        raise RuntimeError("idempotency tombstone lost its command identity")
                    await db.commit()
                    return command, True
                controller = await db.execute(
                    "SELECT accepting_execute FROM controller_state WHERE singleton_id=1"
                )
                if draft.kind == "execute" and not (await controller.fetchone())[0]:
                    raise RuntimeError("CONTROLLER_NOT_ACCEPTING_EXECUTE")
                if draft.kind == "execute":
                    queued_cursor = await db.execute(
                        "SELECT COUNT(*) FROM commands WHERE kind='execute' AND state='queued'"
                    )
                    if int((await queued_cursor.fetchone())[0]) >= self._queue_capacity:
                        raise QueueCapacityExceededError("QUEUE_CAPACITY_EXCEEDED")
                values = draft.model_dump(mode="python")
                insert = await db.execute(
                    """INSERT INTO commands
                    (command_id,caller_scope,request_id,request_hash,kind,mode,
                     payload_json,requested_budget_json,effective_budget_json,state,
                     state_version,accepted_at_ms,queue_deadline_ms,execution_deadline_ms)
                    VALUES (?,?,?,?,?,?,?,?,?,'queued',0,?,?,?)""",
                    (
                        draft.command_id,
                        draft.caller_scope,
                        draft.request_id,
                        draft.request_hash,
                        draft.kind,
                        draft.mode,
                        _dump(values["payload"]),
                        _dump(values["requested_budget"]),
                        _dump(values["effective_budget"]),
                        draft.accepted_at_ms,
                        draft.queue_deadline_ms,
                        draft.execution_deadline_ms,
                    ),
                )
                sequence = insert.lastrowid
                await db.execute(
                    """INSERT INTO idempotency_tombstones
                    (caller_scope,request_id,request_hash,command_id,created_at_ms)
                    VALUES (?,?,?,?,?)""",
                    (
                        draft.caller_scope,
                        draft.request_id,
                        draft.request_hash,
                        draft.command_id,
                        draft.accepted_at_ms,
                    ),
                )
                await db.execute(
                    """INSERT INTO command_transitions
                    (command_id,from_state,to_state,command_version,reason_code,actor,
                     details_json,occurred_at_ms) VALUES (?,NULL,'queued',0,'ACCEPTED',
                     'gateway','{}',?)""",
                    (draft.command_id, draft.accepted_at_ms),
                )
                await db.execute(
                    """UPDATE controller_state SET projection_version=projection_version+1,
                    updated_at_ms=? WHERE singleton_id=1""",
                    (draft.accepted_at_ms,),
                )
                await db.commit()
                return JournalCommand(
                    **draft.model_dump(mode="python"),
                    queue_sequence=int(sequence),
                    state=CommandState.QUEUED,
                    state_version=0,
                ), False
            except Exception:
                await db.rollback()
                raise

    async def get_command(self, command_id: str) -> JournalCommand | None:
        return await self._fetch_command(command_id)

    async def find_by_request(self, caller_scope: str, request_id: str) -> JournalCommand | None:
        cursor = await self._require_db().execute(
            "SELECT command_id FROM commands WHERE caller_scope=? AND request_id=?",
            (caller_scope, request_id),
        )
        row = await cursor.fetchone()
        return await self._fetch_command(row[0]) if row else None

    async def transition(
        self,
        command_id: str,
        *,
        expected_version: int,
        target: CommandState,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        terminal_result: dict[str, Any] | None = None,
    ) -> JournalCommand:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                current = await self._fetch_command(command_id)
                if current is None:
                    raise KeyError(command_id)
                if current.state_version != expected_version:
                    raise StaleCommandVersionError(command_id)
                validate_transition(current.state, target)
                terminal = target in TERMINAL_COMMAND_STATES
                if terminal_result is not None and not terminal:
                    raise ValueError("terminal_result requires a terminal command state")
                started_at = (
                    occurred_at_ms if target is CommandState.RUNNING else current.started_at_ms
                )
                changed = await db.execute(
                    """UPDATE commands SET state=?,state_version=state_version+1,
                    started_at_ms=?,terminal_at_ms=?,terminal_result_json=
                    CASE WHEN ? THEN ? ELSE terminal_result_json END
                    WHERE command_id=? AND state_version=?""",
                    (
                        target.value,
                        started_at,
                        occurred_at_ms if terminal else current.terminal_at_ms,
                        terminal,
                        _dump(terminal_result) if terminal_result is not None else None,
                        command_id,
                        expected_version,
                    ),
                )
                if changed.rowcount != 1:
                    raise StaleCommandVersionError(command_id)
                await db.execute(
                    """INSERT INTO command_transitions
                    (command_id,from_state,to_state,command_version,reason_code,actor,
                     details_json,occurred_at_ms) VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        command_id,
                        current.state.value,
                        target.value,
                        expected_version + 1,
                        reason_code,
                        actor,
                        _dump(details or {}),
                        occurred_at_ms,
                    ),
                )
                if terminal:
                    await db.execute(
                        """UPDATE idempotency_tombstones SET terminal_state=?,terminal_result_hash=?
                        WHERE caller_scope=? AND request_id=?""",
                        (
                            target.value,
                            canonical_json_hash(terminal_result)
                            if terminal_result is not None
                            else None,
                            current.caller_scope,
                            current.request_id,
                        ),
                    )
                await db.execute(
                    """UPDATE controller_state SET projection_version=projection_version+1,
                    updated_at_ms=? WHERE singleton_id=1""",
                    (occurred_at_ms,),
                )
                await db.commit()
                result = await self._fetch_command(command_id)
                assert result is not None
                return result
            except Exception:
                await db.rollback()
                raise

    async def transitions(self, command_id: str) -> list[CommandTransition]:
        cursor = await self._require_db().execute(
            "SELECT * FROM command_transitions WHERE command_id=? ORDER BY transition_id",
            (command_id,),
        )
        return [
            CommandTransition(
                transition_id=row["transition_id"],
                command_id=row["command_id"],
                from_state=row["from_state"],
                to_state=row["to_state"],
                command_version=row["command_version"],
                reason_code=row["reason_code"],
                actor=row["actor"],
                details=json.loads(row["details_json"]),
                occurred_at_ms=row["occurred_at_ms"],
            )
            for row in await cursor.fetchall()
        ]

    @staticmethod
    def _row_to_activity(row: Any) -> ActivityRecord:
        return ActivityRecord(
            sequence=row["activity_sequence"],
            source_key=row["source_key"],
            command_id=row["command_id"],
            caller_scope=row["caller_scope"],
            mission_id=row["mission_id"],
            payload=json.loads(row["payload_json"]),
            occurred_at_ms=row["occurred_at_ms"],
        )

    async def append_activity(
        self,
        draft: ActivityDraft,
        *,
        retention_before_ms: int | None = None,
    ) -> tuple[ActivityRecord, bool]:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing_cursor = await db.execute(
                    "SELECT * FROM public_activity_events WHERE source_key=?",
                    (draft.source_key,),
                )
                existing = await existing_cursor.fetchone()
                if existing is not None:
                    record = self._row_to_activity(existing)
                    if not record.matches(draft):
                        raise ValueError("activity source key conflicts with committed payload")
                    if retention_before_ms is not None:
                        await db.execute(
                            """DELETE FROM public_activity_events
                            WHERE occurred_at_ms<? AND source_key<>?""",
                            (retention_before_ms, record.source_key),
                        )
                    await db.commit()
                    return record, True
                command_cursor = await db.execute(
                    "SELECT caller_scope FROM commands WHERE command_id=?",
                    (draft.command_id,),
                )
                command = await command_cursor.fetchone()
                if command is None or command["caller_scope"] != draft.caller_scope:
                    raise ValueError("activity command scope mismatch")
                if draft.payload.phase != "finished":
                    terminal_cursor = await db.execute(
                        """SELECT 1 FROM public_activity_events
                        WHERE command_id=?
                          AND json_extract(payload_json, '$.phase')='finished'
                        LIMIT 1""",
                        (draft.command_id,),
                    )
                    if await terminal_cursor.fetchone() is not None:
                        raise ValueError("active activity cannot follow terminal activity")
                inserted = await db.execute(
                    """INSERT INTO public_activity_events
                    (source_key,command_id,caller_scope,mission_id,payload_json,occurred_at_ms)
                    VALUES (?,?,?,?,?,?)""",
                    (
                        draft.source_key,
                        draft.command_id,
                        draft.caller_scope,
                        draft.mission_id,
                        _dump(draft.payload.model_dump(mode="json")),
                        draft.occurred_at_ms,
                    ),
                )
                if retention_before_ms is not None:
                    await db.execute(
                        """DELETE FROM public_activity_events
                        WHERE occurred_at_ms<? AND source_key<>?""",
                        (retention_before_ms, draft.source_key),
                    )
                await db.commit()
                return ActivityRecord(
                    sequence=int(inserted.lastrowid),
                    **draft.model_dump(mode="python"),
                ), False
            except Exception:
                await db.rollback()
                raise

    async def read_activity(
        self,
        caller_scope: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ActivityRecordPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = int(cursor) if cursor else 0
        cursor_result = await self._require_db().execute(
            """SELECT * FROM public_activity_events
            WHERE caller_scope=? AND activity_sequence>?
            ORDER BY activity_sequence LIMIT ?""",
            (caller_scope, after, limit + 1),
        )
        rows = await cursor_result.fetchall()
        page_rows = rows[:limit]
        return ActivityRecordPage(
            records=tuple(self._row_to_activity(row) for row in page_rows),
            next_cursor=(str(page_rows[-1]["activity_sequence"]) if len(rows) > limit else None),
        )

    async def expire_activity(self, *, before_ms: int) -> int:
        cursor = await self._require_db().execute(
            "DELETE FROM public_activity_events WHERE occurred_at_ms<?",
            (before_ms,),
        )
        await self._require_db().commit()
        return cursor.rowcount

    async def read_recent_activity(self, *, limit: int = 20) -> ActivityRecordPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        cursor = await self._require_db().execute(
            """SELECT * FROM (
              SELECT * FROM public_activity_events ORDER BY activity_sequence DESC LIMIT ?
            ) ORDER BY activity_sequence""",
            (limit,),
        )
        return ActivityRecordPage(
            records=tuple(self._row_to_activity(row) for row in await cursor.fetchall())
        )

    async def append_receipt(self, command_id: str, ordinal: int, receipt: dict[str, Any]) -> None:
        await self._require_db().execute(
            """INSERT INTO action_receipts
            (receipt_id,command_id,ordinal,receipt_json) VALUES (?,?,?,?)""",
            (receipt["receipt_id"], command_id, ordinal, _dump(receipt)),
        )
        await self._require_db().commit()

    async def save_budget(
        self, command_id: str, settled: dict[str, Any], reserved: dict[str, Any]
    ) -> None:
        await self._require_db().execute(
            """INSERT INTO command_budget_usage
            (command_id,usage_version,settled_usage_json,reserved_usage_json,updated_at_ms)
            VALUES (?,1,?,?,0)
            ON CONFLICT(command_id) DO UPDATE SET usage_version=usage_version+1,
            settled_usage_json=excluded.settled_usage_json,
            reserved_usage_json=excluded.reserved_usage_json""",
            (command_id, _dump(settled), _dump(reserved)),
        )
        await self._require_db().commit()

    async def append_checkpoint(self, command_id: str, checkpoint: dict[str, Any]) -> None:
        payload = dict(checkpoint)
        payload.setdefault("checkpoint_id", f"checkpoint-{uuid4().hex}")
        await self._require_db().execute(
            "INSERT INTO checkpoints VALUES (?,?,?,0)",
            (payload["checkpoint_id"], command_id, _dump(payload)),
        )
        await self._require_db().commit()

    async def append_recovery(self, command_id: str, recovery: dict[str, Any]) -> None:
        payload = dict(recovery)
        payload.setdefault("recovery_id", f"recovery-{uuid4().hex}")
        await self._require_db().execute(
            "INSERT INTO recovery_attempts VALUES (?,?,?,0)",
            (payload["recovery_id"], command_id, _dump(payload)),
        )
        await self._require_db().commit()

    async def command_facts(self, command_id: str) -> dict[str, int]:
        db = self._require_db()
        tables = {
            "receipts": "action_receipts",
            "budgets": "command_budget_usage",
            "checkpoints": "checkpoints",
            "recoveries": "recovery_attempts",
        }
        result = {}
        for name, table in tables.items():
            cursor = await db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE command_id=?", (command_id,)
            )
            result[name] = int((await cursor.fetchone())[0])
        return result

    async def next_eligible(self, *, now_ms: int) -> JournalCommand | None:
        cursor = await self._require_db().execute(
            """SELECT * FROM commands WHERE kind='execute' AND state='queued'
            AND (queue_deadline_ms IS NULL OR queue_deadline_ms>?)
            ORDER BY queue_sequence LIMIT 1""",
            (now_ms,),
        )
        row = await cursor.fetchone()
        return self._row_to_command(row) if row else None

    async def expire_queued(self, *, now_ms: int) -> tuple[str, ...]:
        cursor = await self._require_db().execute(
            """SELECT command_id,state_version FROM commands
            WHERE kind='execute' AND state='queued' AND queue_deadline_ms<=?""",
            (now_ms,),
        )
        expired = []
        for row in await cursor.fetchall():
            try:
                await self.transition(
                    row["command_id"],
                    expected_version=row["state_version"],
                    target=CommandState.FAILED,
                    reason_code="QUEUE_DEADLINE_EXPIRED",
                    actor="worker",
                    occurred_at_ms=now_ms,
                )
                expired.append(row["command_id"])
            except StaleCommandVersionError:
                continue
        return tuple(expired)

    async def reserve_step(self, step: StepRecord) -> None:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    """INSERT INTO command_steps
                    (step_id,command_id,ordinal,strategy_state_hash,capability,params_hash,
                     params_json,correlation_id,runtime_instance_id,state,reservation_json,
                     before_observation_hash,created_at_ms)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                    (
                        step.step_id,
                        step.command_id,
                        step.ordinal,
                        step.strategy_state_hash,
                        step.capability,
                        step.params_hash,
                        _dump(step.params),
                        step.correlation_id,
                        step.runtime_instance_id,
                        step.state,
                        _dump(step.reservation),
                        step.before_observation_hash,
                    ),
                )
                await db.execute(
                    """INSERT INTO command_budget_usage
                    (command_id,usage_version,settled_usage_json,reserved_usage_json,updated_at_ms)
                    VALUES (?,1,'{}',?,0)
                    ON CONFLICT(command_id) DO UPDATE SET
                    usage_version=usage_version+1,
                    reserved_usage_json=excluded.reserved_usage_json""",
                    (step.command_id, _dump(step.reservation)),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def update_step_state(self, step_id: str, state: str) -> StepRecord:
        if state not in {"reserved", "dispatched", "settled", "unknown"}:
            raise ValueError(state)
        await self._require_db().execute(
            "UPDATE command_steps SET state=? WHERE step_id=?", (state, step_id)
        )
        await self._require_db().commit()
        result = await self.get_step(step_id)
        if result is None:
            raise KeyError(step_id)
        return result

    async def get_step(self, step_id: str) -> StepRecord | None:
        cursor = await self._require_db().execute(
            "SELECT * FROM command_steps WHERE step_id=?", (step_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        receipt = None
        if row["receipt_id"]:
            receipt_cursor = await self._require_db().execute(
                "SELECT receipt_json FROM action_receipts WHERE receipt_id=?",
                (row["receipt_id"],),
            )
            receipt_row = await receipt_cursor.fetchone()
            receipt = json.loads(receipt_row[0]) if receipt_row else None
        return StepRecord(
            step_id=row["step_id"],
            command_id=row["command_id"],
            ordinal=row["ordinal"],
            strategy_state_hash=row["strategy_state_hash"],
            capability=row["capability"],
            params_hash=row["params_hash"],
            params=json.loads(row["params_json"]),
            correlation_id=row["correlation_id"],
            runtime_instance_id=row["runtime_instance_id"],
            state=row["state"],
            reservation=json.loads(row["reservation_json"]),
            before_observation_hash=row["before_observation_hash"],
            receipt=receipt,
        )

    async def latest_step(self, command_id: str) -> StepRecord | None:
        cursor = await self._require_db().execute(
            "SELECT step_id FROM command_steps WHERE command_id=? ORDER BY ordinal DESC LIMIT 1",
            (command_id,),
        )
        row = await cursor.fetchone()
        return await self.get_step(row[0]) if row else None

    async def list_steps(self, command_id: str) -> tuple[StepRecord, ...]:
        cursor = await self._require_db().execute(
            "SELECT step_id FROM command_steps WHERE command_id=? ORDER BY ordinal",
            (command_id,),
        )
        rows = await cursor.fetchall()
        steps = [await self.get_step(row[0]) for row in rows]
        return tuple(step for step in steps if step is not None)

    async def _store_receipt(self, db: Any, step: StepRecord, receipt: dict[str, Any]) -> None:
        cursor = await db.execute(
            "SELECT content_hash FROM action_receipts WHERE receipt_id=?",
            (receipt["receipt_id"],),
        )
        existing = await cursor.fetchone()
        if existing is not None:
            if existing["content_hash"] != receipt.get("content_hash"):
                raise ValueError(f"receipt identity collision: {receipt['receipt_id']}")
            return
        await db.execute(
            """INSERT INTO action_receipts
            (receipt_id,command_id,step_id,ordinal,runtime_instance_id,
             correlation_id,previous_receipt_hash,content_hash,outcome,
             before_observation_hash,after_observation_hash,mutations_json,
             budget_delta_json,receipt_json,persisted_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (
                receipt["receipt_id"],
                step.command_id,
                step.step_id,
                step.ordinal,
                receipt.get("runtime_instance_id"),
                receipt.get("correlation_id"),
                receipt.get("previous_receipt_hash", ""),
                receipt.get("content_hash"),
                receipt.get("outcome"),
                receipt.get("before_observation_hash"),
                receipt.get("after_observation_hash"),
                _dump(receipt.get("explained_mutations", [])),
                _dump(receipt.get("budget_usage", {})),
                _dump(receipt),
            ),
        )

    async def record_step_receipt(self, step_id: str, receipt: dict[str, Any]) -> StepRecord:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                step = await self.get_step(step_id)
                if step is None:
                    raise KeyError(step_id)
                await self._store_receipt(db, step, receipt)
                await db.execute(
                    "UPDATE command_steps SET receipt_id=? WHERE step_id=?",
                    (receipt["receipt_id"], step_id),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        result = await self.get_step(step_id)
        if result is None:
            raise KeyError(step_id)
        return result

    async def settle_step(
        self,
        step_id: str,
        receipt: dict[str, Any],
        *,
        settled_usage: dict[str, Any] | None = None,
        reserved_usage: dict[str, Any] | None = None,
    ) -> StepRecord:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                step = await self.get_step(step_id)
                if step is None:
                    raise KeyError(step_id)
                existing_receipt_id = (
                    step.receipt.get("receipt_id") if step.receipt is not None else None
                )
                if existing_receipt_id is not None and existing_receipt_id != receipt["receipt_id"]:
                    raise ValueError(
                        "step settlement receipt conflict: "
                        f"{step_id} already references {existing_receipt_id}"
                    )
                await self._store_receipt(db, step, receipt)
                if step.state != "settled":
                    update = await db.execute(
                        """UPDATE command_steps SET state='settled',receipt_id=?,settled_at_ms=?
                        WHERE step_id=? AND state IN ('reserved','dispatched','unknown')""",
                        (
                            receipt["receipt_id"],
                            int(receipt.get("finished_at_ms", 0)),
                            step_id,
                        ),
                    )
                    if update.rowcount != 1:
                        raise RuntimeError(f"step settlement state conflict: {step_id}")
                    if settled_usage is not None:
                        await db.execute(
                            """UPDATE command_budget_usage SET usage_version=usage_version+1,
                            settled_usage_json=?,reserved_usage_json=? WHERE command_id=?""",
                            (
                                _dump(settled_usage),
                                _dump(reserved_usage or {}),
                                step.command_id,
                            ),
                        )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        result = await self.get_step(step_id)
        assert result is not None
        return result

    async def apply_stop_barrier(
        self, draft: CommandDraft, *, occurred_at_ms: int
    ) -> StopBarrierCommit:
        if draft.kind != "stop":
            raise ValueError("stop barrier requires a stop command")
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """SELECT request_hash,command_id FROM idempotency_tombstones
                    WHERE caller_scope=? AND request_id=?""",
                    (draft.caller_scope, draft.request_id),
                )
                existing = await cursor.fetchone()
                if existing:
                    if existing["request_hash"] != draft.request_hash:
                        raise IdempotencyConflictError("IDEMPOTENCY_CONFLICT")
                    command = await self._fetch_command(existing["command_id"])
                    assert command is not None
                    await db.commit()
                    return StopBarrierCommit(command, True, None, ())
                insert = await db.execute(
                    """INSERT INTO commands
                    (command_id,caller_scope,request_id,request_hash,kind,mode,
                     payload_json,requested_budget_json,effective_budget_json,state,
                     state_version,accepted_at_ms)
                    VALUES (?,?,?,?,? ,NULL,?,?,?,'queued',0,?)""",
                    (
                        draft.command_id,
                        draft.caller_scope,
                        draft.request_id,
                        draft.request_hash,
                        draft.kind,
                        _dump(draft.payload),
                        _dump(draft.requested_budget),
                        _dump(draft.effective_budget),
                        draft.accepted_at_ms,
                    ),
                )
                await db.execute(
                    """INSERT INTO idempotency_tombstones
                    (caller_scope,request_id,request_hash,command_id,created_at_ms)
                    VALUES (?,?,?,?,?)""",
                    (
                        draft.caller_scope,
                        draft.request_id,
                        draft.request_hash,
                        draft.command_id,
                        occurred_at_ms,
                    ),
                )
                await db.execute(
                    """INSERT INTO command_transitions
                    (command_id,from_state,to_state,command_version,reason_code,actor,details_json,occurred_at_ms)
                    VALUES (?,NULL,'queued',0,'STOP_ACCEPTED','gateway','{}',?)""",
                    (draft.command_id, occurred_at_ms),
                )
                pending_cursor = await db.execute(
                    "SELECT command_id,state_version FROM commands WHERE kind='execute' AND state='queued'"
                )
                pending = await pending_cursor.fetchall()
                for row in pending:
                    await db.execute(
                        """UPDATE commands SET state='cancelled_by_stop',state_version=state_version+1,
                        terminal_at_ms=? WHERE command_id=? AND state='queued'""",
                        (occurred_at_ms, row["command_id"]),
                    )
                    await db.execute(
                        """INSERT INTO command_transitions
                        (command_id,from_state,to_state,command_version,reason_code,actor,details_json,occurred_at_ms)
                        VALUES (?,'queued','cancelled_by_stop',?,'GLOBAL_STOP','gateway','{}',?)""",
                        (row["command_id"], row["state_version"] + 1, occurred_at_ms),
                    )
                active_cursor = await db.execute(
                    "SELECT command_id FROM commands WHERE kind='execute' AND state IN ('running','reconciling','blocked_unknown') LIMIT 1"
                )
                active = await active_cursor.fetchone()
                active_id = active[0] if active else None
                if active_id:
                    await db.execute(
                        """UPDATE commands SET cancel_requested_at_ms=COALESCE(cancel_requested_at_ms,?)
                        WHERE command_id=?""",
                        (occurred_at_ms, active_id),
                    )
                await db.execute(
                    """UPDATE controller_state SET state='stopping',accepting_execute=0,
                    stop_barrier_id=?,projection_version=projection_version+1,updated_at_ms=?
                    WHERE singleton_id=1""",
                    (draft.command_id, occurred_at_ms),
                )
                await db.commit()
                stop_command = JournalCommand(
                    **draft.model_dump(mode="python"),
                    queue_sequence=int(insert.lastrowid),
                    state=CommandState.QUEUED,
                    state_version=0,
                )
                return StopBarrierCommit(
                    stop_command, False, active_id, tuple(row["command_id"] for row in pending)
                )
            except Exception:
                await db.rollback()
                raise

    async def recover_startup(self, *, occurred_at_ms: int) -> StartupRecovery:
        cursor = await self._require_db().execute(
            "SELECT * FROM commands WHERE state IN "
            "('queued','running','reconciling','blocked_unknown')"
        )
        interrupted: list[str] = []
        blocked: list[str] = []
        for row in await cursor.fetchall():
            command = self._row_to_command(row)
            if command.state is CommandState.BLOCKED_UNKNOWN:
                blocked.append(command.command_id)
                continue
            target = (
                CommandState.INTERRUPTED_BEFORE_START
                if command.state is CommandState.QUEUED
                else CommandState.BLOCKED_UNKNOWN
            )
            await self.transition(
                command.command_id,
                expected_version=command.state_version,
                target=target,
                reason_code="PROCESS_RESTART",
                actor="startup",
                occurred_at_ms=occurred_at_ms,
            )
            (interrupted if target is CommandState.INTERRUPTED_BEFORE_START else blocked).append(
                command.command_id
            )
        if blocked:
            await self._require_db().execute(
                """UPDATE controller_state SET state='quarantined',accepting_execute=0,
                updated_at_ms=? WHERE singleton_id=1""",
                (occurred_at_ms,),
            )
            await self._require_db().commit()
        return StartupRecovery(tuple(interrupted), tuple(blocked), bool(blocked))

    async def read_projection(
        self, caller_scope: str, *, limit: int = 20, cursor: str | None = None
    ) -> ProjectionPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = int(cursor) if cursor else 0
        db = self._require_db()
        rows_cursor = await db.execute(
            """SELECT * FROM commands WHERE caller_scope=? AND queue_sequence>?
            ORDER BY queue_sequence LIMIT ?""",
            (caller_scope, after, limit + 1),
        )
        rows = await rows_cursor.fetchall()
        page_rows = rows[:limit]
        version_cursor = await db.execute(
            "SELECT projection_version FROM controller_state WHERE singleton_id=1"
        )
        version = int((await version_cursor.fetchone())[0])
        return ProjectionPage(
            projection_version=version,
            commands=tuple(self._row_to_command(row) for row in page_rows),
            next_cursor=str(page_rows[-1]["queue_sequence"]) if len(rows) > limit else None,
        )

    async def expire_terminal_payloads(self, *, before_ms: int) -> int:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    """DELETE FROM public_activity_events WHERE command_id IN (
                      SELECT command_id FROM commands
                      WHERE terminal_at_ms IS NOT NULL AND terminal_at_ms<?
                    )""",
                    (before_ms,),
                )
                cursor = await db.execute(
                    """UPDATE commands SET payload_json='{}',terminal_result_json=NULL
                    WHERE terminal_at_ms IS NOT NULL AND terminal_at_ms<?""",
                    (before_ms,),
                )
                await db.commit()
                return cursor.rowcount
            except Exception:
                await db.rollback()
                raise

    async def pragmas(self) -> dict[str, Any]:
        db = self._require_db()
        result = {}
        for name in ("journal_mode", "foreign_keys", "busy_timeout", "synchronous"):
            cursor = await db.execute(f"PRAGMA {name}")
            result[name] = (await cursor.fetchone())[0]
        return result

    async def index_names(self) -> set[str]:
        cursor = await self._require_db().execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        return {str(row[0]) for row in await cursor.fetchall()}
