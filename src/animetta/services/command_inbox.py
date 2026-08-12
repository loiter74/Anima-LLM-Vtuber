"""Durable single-instance idempotency for user-triggered commands."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger


class CommandStatus(StrEnum):
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class CommandDecision(StrEnum):
    EXECUTE = "execute"
    OBSERVE = "observe"
    REPLAY = "replay"
    TERMINAL = "terminal"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"


ACTIVE_STATUSES = {CommandStatus.ACCEPTED, CommandStatus.PROCESSING}
TERMINAL_STATUSES = {
    CommandStatus.SUCCEEDED,
    CommandStatus.FAILED,
    CommandStatus.CANCELLED,
    CommandStatus.INTERRUPTED,
}


class CommandInboxError(RuntimeError):
    """Base class for command Inbox failures."""


class TaskResultTooLargeError(CommandInboxError):
    """A replay result exceeds the configured durable payload limit."""


@dataclass(frozen=True, slots=True)
class CommandKey:
    scope: str
    kind: str
    task_id: str


@dataclass(frozen=True, slots=True)
class CommandTask:
    key: CommandKey
    request_hash: str
    status: CommandStatus
    progress: dict[str, Any] | None
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at_ms: int
    updated_at_ms: int
    started_at_ms: int | None
    finished_at_ms: int | None
    cancel_requested_at_ms: int | None
    expires_at_ms: int | None
    version: int

    def snapshot(self, *, reused: bool = False) -> dict[str, Any]:
        return {
            "kind": self.key.kind,
            "task_id": self.key.task_id,
            "status": self.status.value,
            "progress": self.progress,
            "result": self.result,
            "error": (
                {"code": self.error_code, "message": self.error_message or ""}
                if self.error_code
                else None
            ),
            "reused": reused,
            "created_at": self.created_at_ms,
            "updated_at": self.updated_at_ms,
        }


@dataclass(frozen=True, slots=True)
class AcceptResult:
    decision: CommandDecision
    task: CommandTask | None


def canonical_json(value: Any) -> str:
    """Serialize validated command identity material deterministically."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_fingerprint(value: Any) -> tuple[str, str]:
    payload = canonical_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), payload


class CommandInbox:
    """SQLite Inbox implementing one accepted execution per command identity.

    The Inbox records command lifecycle and replay-safe results. It deliberately
    does not execute domain work and never retries interrupted commands.
    """

    def __init__(
        self,
        db_path: str | Path = "data/command_inbox.db",
        *,
        retention_seconds: int = 7 * 24 * 60 * 60,
        result_limit_bytes: int = 4 * 1024 * 1024,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.db_path = Path(db_path)
        self.retention_ms = max(1, int(retention_seconds)) * 1000
        self.result_limit_bytes = max(1024, int(result_limit_bytes))
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._db is not None

    async def start(self) -> int:
        """Open the database and interrupt commands left active by a prior process."""
        if self._db is not None:
            return 0
        async with self._start_lock:
            if self._db is not None:
                return 0
            if str(self.db_path) != ":memory:":
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            db = await aiosqlite.connect(str(self.db_path))
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS command_tasks (
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress_json TEXT,
                    result_json TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    started_at_ms INTEGER,
                    finished_at_ms INTEGER,
                    cancel_requested_at_ms INTEGER,
                    expires_at_ms INTEGER,
                    version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (scope, kind, task_id)
                );
                CREATE INDEX IF NOT EXISTS ix_command_tasks_status_updated
                    ON command_tasks(status, updated_at_ms);
                CREATE INDEX IF NOT EXISTS ix_command_tasks_expiry
                    ON command_tasks(expires_at_ms);
                """
            )
            now = _now_ms()
            cursor = await db.execute(
                """
                UPDATE command_tasks
                SET status=?, error_code='SERVER_RESTARTED',
                    error_message='Server restarted before completion',
                    updated_at_ms=?, finished_at_ms=?, expires_at_ms=?, version=version+1
                WHERE status IN (?, ?)
                """,
                (
                    CommandStatus.INTERRUPTED.value,
                    now,
                    now,
                    now + self.retention_ms,
                    CommandStatus.ACCEPTED.value,
                    CommandStatus.PROCESSING.value,
                ),
            )
            recovered = max(0, cursor.rowcount)
            await db.commit()
            self._db = db
            await self.cleanup_expired()
            return recovered

    async def close(self) -> None:
        async with self._lock:
            if self._db is None:
                return
            await self._db.close()
            self._db = None

    async def accept(
        self,
        key: CommandKey,
        request: Any,
        *,
        stored_request: Any | None = None,
    ) -> AcceptResult:
        """Atomically accept or classify one validated command."""
        _validate_key(key)
        digest, request_json = request_fingerprint(request)
        if stored_request is not None:
            request_json = canonical_json(stored_request)
        db = await self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._select(db, key)
                if row is None:
                    now = _now_ms()
                    await db.execute(
                        """
                        INSERT INTO command_tasks(
                            scope, kind, task_id, request_hash, request_json, status,
                            created_at_ms, updated_at_ms, version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            key.scope,
                            key.kind,
                            key.task_id,
                            digest,
                            request_json,
                            CommandStatus.ACCEPTED.value,
                            now,
                            now,
                        ),
                    )
                    await db.commit()
                    accepted = AcceptResult(
                        CommandDecision.EXECUTE,
                        await self._get_unlocked(db, key),
                    )
                    _log_accept(key, accepted)
                    return accepted
                task = _row_to_task(row)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        if task.request_hash != digest:
            accepted = AcceptResult(CommandDecision.CONFLICT, task)
        elif task.status in ACTIVE_STATUSES:
            accepted = AcceptResult(CommandDecision.OBSERVE, task)
        elif task.status is CommandStatus.SUCCEEDED:
            accepted = AcceptResult(CommandDecision.REPLAY, task)
        else:
            accepted = AcceptResult(CommandDecision.TERMINAL, task)
        _log_accept(key, accepted)
        return accepted

    async def get(self, key: CommandKey) -> AcceptResult:
        _validate_key(key)
        db = await self._require_db()
        async with self._lock:
            task = await self._get_unlocked(db, key)
        if task is None:
            return AcceptResult(CommandDecision.NOT_FOUND, None)
        return AcceptResult(_decision_for_existing(task), task)

    async def latest(
        self,
        *,
        scope: str,
        kind: str,
        status: CommandStatus | None = None,
    ) -> CommandTask | None:
        db = await self._require_db()
        async with self._lock:
            if status is None:
                query = """
                    SELECT * FROM command_tasks
                    WHERE scope=? AND kind=?
                    ORDER BY created_at_ms DESC LIMIT 1
                """
                parameters: tuple[object, ...] = (scope, kind)
            else:
                query = """
                    SELECT * FROM command_tasks
                    WHERE scope=? AND kind=? AND status=?
                    ORDER BY created_at_ms DESC LIMIT 1
                """
                parameters = (scope, kind, status.value)
            cursor = await db.execute(query, parameters)
            row = await cursor.fetchone()
        return _row_to_task(row) if row is not None else None

    async def mark_processing(self, key: CommandKey) -> CommandTask:
        return await self._transition(
            key,
            from_statuses={CommandStatus.ACCEPTED},
            to_status=CommandStatus.PROCESSING,
            started=True,
        )

    async def update_progress(self, key: CommandKey, progress: dict[str, Any]) -> CommandTask:
        return await self._transition(
            key,
            from_statuses=ACTIVE_STATUSES,
            to_status=None,
            progress=progress,
        )

    async def succeed(self, key: CommandKey, result: dict[str, Any]) -> CommandTask:
        result_json = canonical_json(result)
        if len(result_json.encode("utf-8")) > self.result_limit_bytes:
            failed = await self.fail(
                key,
                error_code="TASK_RESULT_TOO_LARGE",
                error_message="Replay-safe command result exceeds the durable payload limit",
            )
            if failed.status is not CommandStatus.FAILED:
                return failed
            raise TaskResultTooLargeError("TASK_RESULT_TOO_LARGE")
        return await self._transition(
            key,
            from_statuses=ACTIVE_STATUSES,
            to_status=CommandStatus.SUCCEEDED,
            result_json=result_json,
            finished=True,
        )

    async def fail(
        self,
        key: CommandKey,
        *,
        error_code: str,
        error_message: str,
    ) -> CommandTask:
        return await self._transition(
            key,
            from_statuses=ACTIVE_STATUSES,
            to_status=CommandStatus.FAILED,
            error_code=error_code,
            error_message=error_message[:512],
            finished=True,
        )

    async def request_cancel(self, key: CommandKey) -> CommandTask:
        return await self._transition(
            key,
            from_statuses=ACTIVE_STATUSES,
            to_status=None,
            cancel_requested=True,
        )

    async def cancel(self, key: CommandKey, *, message: str = "Cancelled") -> CommandTask:
        return await self._transition(
            key,
            from_statuses=ACTIVE_STATUSES,
            to_status=CommandStatus.CANCELLED,
            error_code="CANCELLED",
            error_message=message[:512],
            finished=True,
        )

    async def cleanup_expired(self, *, limit: int = 500) -> int:
        db = await self._require_db()
        async with self._lock:
            cursor = await db.execute(
                """
                DELETE FROM command_tasks WHERE rowid IN (
                    SELECT rowid FROM command_tasks
                    WHERE expires_at_ms IS NOT NULL AND expires_at_ms <= ?
                    ORDER BY expires_at_ms LIMIT ?
                )
                """,
                (_now_ms(), max(1, int(limit))),
            )
            await db.commit()
            return max(0, cursor.rowcount)

    async def _transition(
        self,
        key: CommandKey,
        *,
        from_statuses: set[CommandStatus],
        to_status: CommandStatus | None,
        progress: dict[str, Any] | None = None,
        result_json: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        started: bool = False,
        finished: bool = False,
        cancel_requested: bool = False,
    ) -> CommandTask:
        db = await self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                row = await self._select(db, key)
                if row is None:
                    raise CommandInboxError("TASK_NOT_FOUND")
                current = _row_to_task(row)
                if current.status not in from_statuses:
                    await db.commit()
                    return current
                now = _now_ms()
                status = to_status or current.status
                expires_at = now + self.retention_ms if status in TERMINAL_STATUSES else None
                await db.execute(
                    """
                    UPDATE command_tasks SET
                        status=?, progress_json=COALESCE(?, progress_json),
                        result_json=COALESCE(?, result_json), error_code=?, error_message=?,
                        started_at_ms=CASE WHEN ? THEN COALESCE(started_at_ms, ?) ELSE started_at_ms END,
                        finished_at_ms=CASE WHEN ? THEN ? ELSE finished_at_ms END,
                        cancel_requested_at_ms=CASE WHEN ? THEN COALESCE(cancel_requested_at_ms, ?) ELSE cancel_requested_at_ms END,
                        expires_at_ms=?, updated_at_ms=?, version=version+1
                    WHERE scope=? AND kind=? AND task_id=? AND version=?
                    """,
                    (
                        status.value,
                        canonical_json(progress) if progress is not None else None,
                        result_json,
                        error_code,
                        error_message,
                        1 if started else 0,
                        now,
                        1 if finished else 0,
                        now,
                        1 if cancel_requested else 0,
                        now,
                        expires_at,
                        now,
                        key.scope,
                        key.kind,
                        key.task_id,
                        current.version,
                    ),
                )
                await db.commit()
                updated = await self._get_unlocked(db, key)
                if updated is None:
                    raise CommandInboxError("TASK_NOT_FOUND")
                return updated
            except Exception:
                await db.rollback()
                raise

    async def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.start()
        assert self._db is not None
        return self._db

    @staticmethod
    async def _select(db: aiosqlite.Connection, key: CommandKey) -> aiosqlite.Row | None:
        cursor = await db.execute(
            "SELECT * FROM command_tasks WHERE scope=? AND kind=? AND task_id=?",
            (key.scope, key.kind, key.task_id),
        )
        return await cursor.fetchone()

    async def _get_unlocked(
        self,
        db: aiosqlite.Connection,
        key: CommandKey,
    ) -> CommandTask | None:
        row = await self._select(db, key)
        return _row_to_task(row) if row is not None else None


def _validate_key(key: CommandKey) -> None:
    for name, value in (("scope", key.scope), ("kind", key.kind), ("task_id", key.task_id)):
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError(f"{name} must be a non-empty string of at most 256 characters")


def _decision_for_existing(task: CommandTask) -> CommandDecision:
    if task.status in ACTIVE_STATUSES:
        return CommandDecision.OBSERVE
    if task.status is CommandStatus.SUCCEEDED:
        return CommandDecision.REPLAY
    return CommandDecision.TERMINAL


def _log_accept(key: CommandKey, accepted: AcceptResult) -> None:
    task = accepted.task
    logger.info(
        "[CommandInbox] kind={} task_id={} decision={} status={} hash={}",
        key.kind,
        key.task_id,
        accepted.decision.value,
        task.status.value if task else "missing",
        task.request_hash[:12] if task else "",
    )


def _json_object(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    value = json.loads(raw)
    return value if isinstance(value, dict) else None


def _row_to_task(row: aiosqlite.Row) -> CommandTask:
    return CommandTask(
        key=CommandKey(scope=row["scope"], kind=row["kind"], task_id=row["task_id"]),
        request_hash=row["request_hash"],
        status=CommandStatus(row["status"]),
        progress=_json_object(row["progress_json"]),
        result=_json_object(row["result_json"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at_ms=row["created_at_ms"],
        updated_at_ms=row["updated_at_ms"],
        started_at_ms=row["started_at_ms"],
        finished_at_ms=row["finished_at_ms"],
        cancel_requested_at_ms=row["cancel_requested_at_ms"],
        expires_at_ms=row["expires_at_ms"],
        version=row["version"],
    )


def _now_ms() -> int:
    return time.time_ns() // 1_000_000
