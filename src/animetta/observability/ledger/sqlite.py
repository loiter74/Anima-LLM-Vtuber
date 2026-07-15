"""Application-owned SQLite observation ledger with one async writer."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import aiosqlite

from ..domain import (
    CommittedObservation,
    ContentFacts,
    ObservationEvent,
    ObservationHealth,
    OperationFinished,
    OperationStarted,
    TraceFinished,
    TraceOutcome,
    TraceStarted,
)
from ..ports import ObservationMirror

SCHEMA_VERSION = 2


class LedgerError(RuntimeError):
    """Base class for local observation ledger errors."""


class LedgerIntegrityError(LedgerError):
    """A command violates trace lifecycle or parentage invariants."""


class LedgerWriteError(LedgerError):
    """A queued SQLite command failed to commit."""


@dataclass(slots=True)
class _Command:
    kind: Literal[
        "trace_start",
        "trace_finish",
        "operation_start",
        "operation_finish",
        "event",
        "inspection_report",
        "readiness_probe",
        "barrier",
        "stop",
    ]
    payload: object | None = None
    acknowledgement: asyncio.Future[None] | None = None


class SQLiteObservationLedger:
    """Single-writer local ledger implementing recorder, query, and report ports."""

    def __init__(
        self,
        db_path: str | Path = "data/observations.db",
        *,
        queue_capacity: int = 4096,
        busy_timeout_ms: int = 5000,
        drain_timeout: float = 5.0,
        mirrors: Sequence[ObservationMirror] = (),
    ) -> None:
        self.db_path = Path(db_path)
        self.queue_capacity = max(1, int(queue_capacity))
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self.drain_timeout = max(0.1, float(drain_timeout))
        self._mirrors = tuple(mirrors)
        self._queue: asyncio.Queue[_Command] = asyncio.Queue(self.queue_capacity)
        self._db: aiosqlite.Connection | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._mirror_tasks: set[asyncio.Task[None]] = set()
        self._started = False
        self._closing = False
        self._dropped_records = 0
        self._writer_errors = 0
        self._mirror_errors = 0
        self._mirror_last_error: str | None = None
        self._stale_traces_recovered = 0
        self._last_error: str | None = None
        self._pending_error: LedgerWriteError | None = None
        self._critical_operation_ids: set[str] = set()

    async def start(self) -> None:
        if self._started:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        await self._create_schema()
        self._stale_traces_recovered = await self._recover_stale_traces()
        self._queue = asyncio.Queue(self.queue_capacity)
        self._closing = False
        self._started = True
        self._writer_task = asyncio.create_task(
            self._writer_loop(), name="animetta-observation-ledger-writer"
        )

    async def close(self) -> None:
        if not self._started:
            return
        try:
            # Shutdown must still release the writer after surfacing a queued
            # failure through health().
            with suppress(LedgerWriteError):
                await self.flush()
            self._closing = True
            acknowledgement = asyncio.get_running_loop().create_future()
            await self._queue.put(_Command("stop", acknowledgement=acknowledgement))
            await asyncio.wait_for(acknowledgement, timeout=self.drain_timeout)
            if self._writer_task is not None:
                await asyncio.wait_for(self._writer_task, timeout=self.drain_timeout)
        finally:
            for task in tuple(self._mirror_tasks):
                task.cancel()
            if self._mirror_tasks:
                await asyncio.gather(*self._mirror_tasks, return_exceptions=True)
            self._mirror_tasks.clear()
            for mirror in self._mirrors:
                close = getattr(mirror, "close", None)
                if close is not None:
                    with suppress(Exception):
                        await close()
            if self._db is not None:
                await self._db.close()
            self._db = None
            self._writer_task = None
            self._started = False
            self._closing = False
            self._critical_operation_ids.clear()

    async def start_trace(self, record: TraceStarted) -> None:
        await self._submit_confirmed(_Command("trace_start", record))

    async def finish_trace(
        self,
        trace_id: str,
        outcome: TraceOutcome,
        *,
        finished_at: float,
        error_type: str | None = None,
        error_summary: str | None = None,
        assistant_content: ContentFacts | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        record = TraceFinished(
            trace_id=trace_id,
            outcome=outcome,
            finished_at=finished_at,
            error_type=error_type,
            error_summary=error_summary,
            assistant_content=assistant_content,
            attributes=attributes or {},
        )
        await self._submit_confirmed(_Command("trace_finish", record))
        self._raise_pending_error()

    async def start_operation(self, record: OperationStarted) -> None:
        if record.critical_path:
            self._critical_operation_ids.add(record.operation_id)
            await self._submit_guaranteed(_Command("operation_start", record))
        else:
            self._submit_noncritical(_Command("operation_start", record))

    async def finish_operation(self, record: OperationFinished) -> None:
        if record.operation_id in self._critical_operation_ids:
            self._critical_operation_ids.discard(record.operation_id)
            await self._submit_guaranteed(_Command("operation_finish", record))
        else:
            self._submit_noncritical(_Command("operation_finish", record))

    async def record_event(self, record: ObservationEvent) -> None:
        self._submit_noncritical(_Command("event", record))

    async def flush(self) -> None:
        self._ensure_started()
        acknowledgement = asyncio.get_running_loop().create_future()
        await self._queue.put(_Command("barrier", acknowledgement=acknowledgement))
        await acknowledgement
        self._raise_pending_error()

    async def probe_write(self) -> None:
        """Commit one bounded health row to prove the ledger remains writable."""
        await self._submit_confirmed(_Command("readiness_probe", time.time()))

    async def health(self) -> ObservationHealth:
        writer_failed = bool(self._writer_task and self._writer_task.done())
        mirror_health = await asyncio.gather(
            *(mirror.health() for mirror in self._mirrors),
            return_exceptions=True,
        )
        mirror_errors = self._mirror_errors
        mirror_last_error: str | None = self._mirror_last_error
        mirror_degraded = False
        for result in mirror_health:
            if isinstance(result, BaseException):
                mirror_errors += 1
                mirror_degraded = True
                mirror_last_error = f"{type(result).__name__}: {result}"[:200]
            else:
                mirror_errors += result.writer_errors
                mirror_degraded = mirror_degraded or result.degraded
                mirror_last_error = result.last_error or mirror_last_error
        degraded = bool(
            self._writer_errors
            or self._mirror_errors
            or self._dropped_records
            or writer_failed
            or self._last_error
            or mirror_degraded
        )
        return ObservationHealth(
            enabled=True,
            ready=self._started and not writer_failed,
            degraded=degraded,
            queue_depth=self._queue.qsize(),
            dropped_records=self._dropped_records,
            writer_errors=self._writer_errors + mirror_errors,
            stale_traces_recovered=self._stale_traces_recovered,
            last_error=self._last_error or mirror_last_error,
        )

    async def observation_health(self) -> ObservationHealth:
        return await self.health()

    async def overview(self) -> Mapping[str, Any]:
        db = self._require_db()
        row = await (
            await db.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS success,
                       SUM(CASE WHEN outcome='degraded' THEN 1 ELSE 0 END) AS degraded,
                       SUM(CASE WHEN outcome='failed' THEN 1 ELSE 0 END) AS failed,
                       AVG(duration_ms) AS average_duration
                FROM observation_traces
                """
            )
        ).fetchone()
        total = int(row["total"] or 0)
        return {
            "schema_version": SCHEMA_VERSION,
            "total_requests": total,
            "success_count": int(row["success"] or 0),
            "degraded_count": int(row["degraded"] or 0),
            "failed_count": int(row["failed"] or 0),
            "success_rate": (round(float(row["success"] or 0) / total * 100, 1) if total else 0.0),
            "avg_duration_ms": round(float(row["average_duration"] or 0.0), 2),
        }

    async def recent_traces(self, limit: int = 50, offset: int = 0) -> Sequence[Mapping[str, Any]]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT trace_id, message_id, conversation_id, session_id,
                   runtime_profile, input_type, privacy_mode, started_at,
                   finished_at, duration_ms, outcome, error_type
            FROM observation_traces
            ORDER BY started_at DESC LIMIT ? OFFSET ?
            """,
            (max(1, min(int(limit), 500)), max(0, int(offset))),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def operation_aggregates(self) -> Sequence[Mapping[str, Any]]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT layer, name, provider, model, COUNT(*) AS operation_count,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count,
                   SUM(CASE WHEN status='degraded' THEN 1 ELSE 0 END) AS degraded_count,
                   SUM(CASE WHEN status IN ('error', 'cancelled') THEN 1 ELSE 0 END)
                       AS failure_count,
                   AVG(duration_ms) AS avg_duration_ms
            FROM observation_operations
            GROUP BY layer, name, provider, model
            ORDER BY operation_count DESC, layer, name
            """
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def trace_detail(self, trace_id: str) -> Mapping[str, Any] | None:
        db = self._require_db()
        trace = await (
            await db.execute("SELECT * FROM observation_traces WHERE trace_id=?", (trace_id,))
        ).fetchone()
        if trace is None:
            return None
        operation_cursor = await db.execute(
            """
            SELECT * FROM observation_operations
            WHERE trace_id=? ORDER BY started_at, operation_id
            """,
            (trace_id,),
        )
        event_cursor = await db.execute(
            """
            SELECT * FROM observation_events
            WHERE trace_id=? ORDER BY occurred_at, event_id
            """,
            (trace_id,),
        )
        detail = dict(trace)
        detail["attributes"] = _json_loads(detail.pop("attributes_json"))
        operations = [self._operation_row(row) for row in await operation_cursor.fetchall()]
        events = [self._event_row(row) for row in await event_cursor.fetchall()]
        post_turn_operations = [
            operation for operation in operations if not operation["critical_path"]
        ]
        detail["operations"] = operations
        detail["operation_tree"] = self._operation_tree(operations)
        detail["events"] = events
        detail["post_turn"] = {
            "pending": sum(item["status"] is None for item in post_turn_operations),
            "completed": sum(
                item["status"] in {"success", "skipped", "degraded"}
                for item in post_turn_operations
            ),
            "failed": sum(
                item["status"] in {"error", "cancelled"} for item in post_turn_operations
            ),
            "operations": post_turn_operations,
        }
        detail["schema_version"] = SCHEMA_VERSION
        return detail

    async def trace_events(self, trace_id: str) -> Sequence[Mapping[str, Any]]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT * FROM observation_events
            WHERE trace_id=? ORDER BY occurred_at, event_id
            """,
            (trace_id,),
        )
        return [self._event_row(row) for row in await cursor.fetchall()]

    async def store_inspection_report(self, report: Mapping[str, Any]) -> None:
        await self._submit_confirmed(_Command("inspection_report", dict(report)))

    async def latest_inspection_report(self) -> Mapping[str, Any] | None:
        db = self._require_db()
        row = await (
            await db.execute("SELECT * FROM inspection_reports ORDER BY started_at DESC LIMIT 1")
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["checks"] = _json_loads(result.pop("checks_json"))
        result["overall_ok"] = bool(result["overall_ok"])
        return result

    async def inspection_reports(
        self, limit: int = 50, offset: int = 0
    ) -> Sequence[Mapping[str, Any]]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT * FROM inspection_reports
            ORDER BY started_at DESC LIMIT ? OFFSET ?
            """,
            (max(1, min(int(limit), 500)), max(0, int(offset))),
        )
        reports: list[dict[str, Any]] = []
        for row in await cursor.fetchall():
            report = dict(row)
            report["checks"] = _json_loads(report.pop("checks_json"))
            report["overall_ok"] = bool(report["overall_ok"])
            reports.append(report)
        return reports

    async def _submit_confirmed(self, command: _Command) -> None:
        self._ensure_started()
        acknowledgement = asyncio.get_running_loop().create_future()
        command.acknowledgement = acknowledgement
        await self._queue.put(command)
        await acknowledgement

    async def _submit_guaranteed(self, command: _Command) -> None:
        self._ensure_started()
        await self._queue.put(command)

    def _submit_noncritical(self, command: _Command) -> None:
        self._ensure_started()
        try:
            self._queue.put_nowait(command)
        except asyncio.QueueFull:
            self._dropped_records += 1

    def _ensure_started(self) -> None:
        if not self._started or self._db is None:
            raise LedgerError("observation ledger is not started")
        if self._closing:
            raise LedgerError("observation ledger is closing")

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise LedgerError("observation ledger is not started")
        return self._db

    async def _writer_loop(self) -> None:
        while True:
            command = await self._queue.get()
            try:
                if command.kind == "stop":
                    await self._require_db().commit()
                    _resolve(command.acknowledgement)
                    return
                if command.kind == "barrier":
                    await self._require_db().commit()
                    _resolve(command.acknowledgement)
                    continue

                committed = await self._execute(command)
                await self._require_db().commit()
                _resolve(command.acknowledgement)
                if committed is not None:
                    self._publish(committed)
            except LedgerIntegrityError as exc:
                await self._require_db().rollback()
                if command.acknowledgement is not None:
                    _reject(command.acknowledgement, exc)
                else:
                    self._record_writer_error(LedgerWriteError(str(exc)))
            except Exception as exc:
                await self._require_db().rollback()
                wrapped = LedgerWriteError(f"{command.kind} commit failed: {type(exc).__name__}")
                self._record_writer_error(wrapped)
                if command.acknowledgement is not None:
                    _reject(command.acknowledgement, wrapped)
            finally:
                self._queue.task_done()

    async def _execute(self, command: _Command) -> CommittedObservation | None:
        if command.kind == "trace_start":
            record = _expect(command.payload, TraceStarted)
            await self._insert_trace(record)
            return record
        if command.kind == "trace_finish":
            record = _expect(command.payload, TraceFinished)
            await self._finish_trace_record(record)
            return record
        if command.kind == "operation_start":
            record = _expect(command.payload, OperationStarted)
            await self._insert_operation(record)
            return record
        if command.kind == "operation_finish":
            record = _expect(command.payload, OperationFinished)
            await self._finish_operation_record(record)
            return record
        if command.kind == "event":
            record = _expect(command.payload, ObservationEvent)
            await self._insert_event(record)
            return record
        if command.kind == "inspection_report":
            await self._insert_inspection_report(_expect_mapping(command.payload))
            return None
        if command.kind == "readiness_probe":
            if not isinstance(command.payload, (int, float)):
                raise LedgerIntegrityError("invalid readiness probe timestamp")
            await self._require_db().execute(
                """
                INSERT INTO observation_readiness_probe (id, checked_at)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET checked_at=excluded.checked_at
                """,
                (float(command.payload),),
            )
            return None
        raise LedgerIntegrityError(f"unsupported ledger command: {command.kind}")

    async def _insert_trace(self, record: TraceStarted) -> None:
        user = record.user_content
        try:
            await self._require_db().execute(
                """
                INSERT INTO observation_traces (
                    trace_id, message_id, conversation_id, session_id,
                    runtime_profile, input_type, privacy_mode, started_at,
                    user_text, user_character_count, user_byte_count, user_digest,
                    attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.trace_id,
                    record.identity.message_id,
                    record.identity.conversation_id,
                    record.identity.session_id,
                    record.runtime_profile,
                    record.input_type,
                    record.privacy_mode.value,
                    record.started_at,
                    user.text if user else None,
                    user.character_count if user else None,
                    user.byte_count if user else None,
                    user.digest if user else None,
                    _json_dumps(record.attributes),
                ),
            )
        except aiosqlite.IntegrityError as exc:
            raise LedgerIntegrityError(f"trace already exists: {record.trace_id}") from exc

    async def _finish_trace_record(self, record: TraceFinished) -> None:
        db = self._require_db()
        open_critical = await (
            await db.execute(
                """
                SELECT COUNT(*) FROM observation_operations
                WHERE trace_id=? AND critical_path=1 AND status IS NULL
                """,
                (record.trace_id,),
            )
        ).fetchone()
        if int(open_critical[0]) > 0:
            raise LedgerIntegrityError(f"trace {record.trace_id} has running critical operations")
        started = await (
            await db.execute(
                "SELECT started_at FROM observation_traces WHERE trace_id=?",
                (record.trace_id,),
            )
        ).fetchone()
        if started is None:
            raise LedgerIntegrityError(f"trace does not exist: {record.trace_id}")
        duration_ms = max(0.0, (record.finished_at - float(started[0])) * 1000)
        assistant = record.assistant_content
        cursor = await db.execute(
            """
            UPDATE observation_traces
            SET finished_at=?, duration_ms=?, outcome=?, error_type=?, error_summary=?,
                assistant_text=?, assistant_character_count=?, assistant_byte_count=?,
                assistant_digest=?, attributes_json=?
            WHERE trace_id=? AND outcome IS NULL
            """,
            (
                record.finished_at,
                duration_ms,
                record.outcome.value,
                record.error_type,
                record.error_summary,
                assistant.text if assistant else None,
                assistant.character_count if assistant else None,
                assistant.byte_count if assistant else None,
                assistant.digest if assistant else None,
                _json_dumps(record.attributes),
                record.trace_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LedgerIntegrityError(f"trace already finalized: {record.trace_id}")

    async def _insert_operation(self, record: OperationStarted) -> None:
        try:
            await self._require_db().execute(
                """
                INSERT INTO observation_operations (
                    operation_id, trace_id, parent_operation_id, layer, name,
                    critical_path, started_at, provider, model, attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.operation_id,
                    record.trace_id,
                    record.parent_operation_id,
                    record.layer.value,
                    record.name,
                    int(record.critical_path),
                    record.started_at,
                    record.provider,
                    record.model,
                    _json_dumps(record.attributes),
                ),
            )
        except aiosqlite.IntegrityError as exc:
            raise LedgerIntegrityError(
                f"invalid trace or parent for operation {record.operation_id}"
            ) from exc

    async def _finish_operation_record(self, record: OperationFinished) -> None:
        db = self._require_db()
        started = await (
            await db.execute(
                "SELECT started_at FROM observation_operations WHERE operation_id=?",
                (record.operation_id,),
            )
        ).fetchone()
        if started is None:
            raise LedgerIntegrityError(f"operation does not exist: {record.operation_id}")
        duration_ms = max(0.0, (record.finished_at - float(started[0])) * 1000)
        cursor = await db.execute(
            """
            UPDATE observation_operations
            SET finished_at=?, duration_ms=?, status=?, error_type=?,
                error_summary=?, attributes_json=?
            WHERE operation_id=? AND status IS NULL
            """,
            (
                record.finished_at,
                duration_ms,
                record.status.value,
                record.error_type,
                record.error_summary,
                _json_dumps(record.attributes),
                record.operation_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LedgerIntegrityError(f"operation already finalized: {record.operation_id}")

    async def _insert_event(self, record: ObservationEvent) -> None:
        try:
            await self._require_db().execute(
                """
                INSERT INTO observation_events (
                    event_id, trace_id, operation_id, direction, name, phase,
                    occurred_at, payload_size, identity_valid, attributes_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.event_id,
                    record.trace_id,
                    record.operation_id,
                    record.direction.value,
                    record.name,
                    record.phase,
                    record.occurred_at,
                    max(0, record.payload_size),
                    int(record.identity_valid),
                    _json_dumps(record.attributes),
                ),
            )
        except aiosqlite.IntegrityError as exc:
            raise LedgerIntegrityError(
                f"invalid trace or operation for event {record.event_id}"
            ) from exc

    async def _insert_inspection_report(self, report: Mapping[str, Any]) -> None:
        run_id = str(report["run_id"])
        await self._require_db().execute(
            """
            INSERT OR REPLACE INTO inspection_reports (
                run_id, started_at, finished_at, overall_ok, checks_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                float(report["started_at"]),
                float(report["finished_at"]),
                int(bool(report["overall_ok"])),
                _json_dumps(report.get("checks", {})),
            ),
        )

    async def _create_schema(self) -> None:
        db = self._require_db()
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS observation_schema (
                version INTEGER NOT NULL
            );
            DELETE FROM observation_schema;
            INSERT INTO observation_schema(version) VALUES (2);

            CREATE TABLE IF NOT EXISTS observation_traces (
                trace_id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                runtime_profile TEXT NOT NULL,
                input_type TEXT NOT NULL,
                privacy_mode TEXT NOT NULL,
                started_at REAL NOT NULL,
                finished_at REAL,
                duration_ms REAL,
                outcome TEXT,
                error_type TEXT,
                error_summary TEXT,
                user_text TEXT,
                user_character_count INTEGER,
                user_byte_count INTEGER,
                user_digest TEXT,
                assistant_text TEXT,
                assistant_character_count INTEGER,
                assistant_byte_count INTEGER,
                assistant_digest TEXT,
                attributes_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS observation_operations (
                operation_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL REFERENCES observation_traces(trace_id) ON DELETE CASCADE,
                parent_operation_id TEXT REFERENCES observation_operations(operation_id),
                layer TEXT NOT NULL,
                name TEXT NOT NULL,
                critical_path INTEGER NOT NULL,
                started_at REAL NOT NULL,
                finished_at REAL,
                duration_ms REAL,
                status TEXT,
                provider TEXT,
                model TEXT,
                error_type TEXT,
                error_summary TEXT,
                attributes_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS observation_events (
                event_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL REFERENCES observation_traces(trace_id) ON DELETE CASCADE,
                operation_id TEXT REFERENCES observation_operations(operation_id),
                direction TEXT NOT NULL,
                name TEXT NOT NULL,
                phase TEXT NOT NULL,
                occurred_at REAL NOT NULL,
                payload_size INTEGER NOT NULL,
                identity_valid INTEGER NOT NULL,
                attributes_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS inspection_reports (
                run_id TEXT PRIMARY KEY,
                started_at REAL NOT NULL,
                finished_at REAL NOT NULL,
                overall_ok INTEGER NOT NULL,
                checks_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS observation_readiness_probe (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                checked_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_observation_traces_started
                ON observation_traces(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_observation_operations_trace
                ON observation_operations(trace_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_observation_operations_parent
                ON observation_operations(parent_operation_id);
            CREATE INDEX IF NOT EXISTS idx_observation_events_trace
                ON observation_events(trace_id, occurred_at);
            """
        )
        await db.commit()

    async def _recover_stale_traces(self) -> int:
        db = self._require_db()
        now = time.time()
        cursor = await db.execute(
            """
            UPDATE observation_traces
            SET outcome='aborted', finished_at=?,
                duration_ms=MAX(0, (? - started_at) * 1000),
                error_type='process_aborted',
                error_summary='process ended before trace finalization'
            WHERE outcome IS NULL
            """,
            (now, now),
        )
        await db.commit()
        return max(0, int(cursor.rowcount))

    def _record_writer_error(self, error: LedgerWriteError) -> None:
        self._writer_errors += 1
        self._last_error = str(error)[:200]
        self._pending_error = error

    def _raise_pending_error(self) -> None:
        error = self._pending_error
        self._pending_error = None
        if error is not None:
            raise error

    def _publish(self, record: CommittedObservation) -> None:
        for mirror in self._mirrors:
            task = asyncio.create_task(mirror.publish(record))
            self._mirror_tasks.add(task)
            task.add_done_callback(self._on_mirror_done)

    def _on_mirror_done(self, task: asyncio.Task[None]) -> None:
        self._mirror_tasks.discard(task)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            self._mirror_errors += 1
            self._mirror_last_error = f"{type(error).__name__}: {error}"[:200]

    @staticmethod
    def _operation_row(row: aiosqlite.Row) -> dict[str, Any]:
        result = dict(row)
        result["critical_path"] = bool(result["critical_path"])
        result["attributes"] = _json_loads(result.pop("attributes_json"))
        return result

    @staticmethod
    def _event_row(row: aiosqlite.Row) -> dict[str, Any]:
        result = dict(row)
        result["identity_valid"] = bool(result["identity_valid"])
        result["attributes"] = _json_loads(result.pop("attributes_json"))
        return result

    @staticmethod
    def _operation_tree(
        operations: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        nodes = {
            str(operation["operation_id"]): {**operation, "children": []}
            for operation in operations
        }
        roots: list[dict[str, Any]] = []
        for operation in operations:
            node = nodes[str(operation["operation_id"])]
            parent_id = operation["parent_operation_id"]
            parent = nodes.get(str(parent_id)) if parent_id is not None else None
            if parent is None:
                roots.append(node)
            else:
                parent["children"].append(node)
        return roots


def _resolve(future: asyncio.Future[None] | None) -> None:
    if future is not None and not future.done():
        future.set_result(None)


def _reject(future: asyncio.Future[None], error: BaseException) -> None:
    if not future.done():
        future.set_exception(error)


def _expect(value: object | None, expected_type: type[Any]) -> Any:
    if not isinstance(value, expected_type):
        raise LedgerIntegrityError(f"expected {expected_type.__name__}, got {type(value).__name__}")
    return value


def _expect_mapping(value: object | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LedgerIntegrityError("inspection report must be a mapping")
    return value


def _json_dumps(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}
