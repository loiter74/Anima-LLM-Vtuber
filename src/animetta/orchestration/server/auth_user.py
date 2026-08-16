"""Persistent browser users kept separate from runtime orchestration state."""

from __future__ import annotations

import asyncio
import time
import unicodedata
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import aiosqlite
from loguru import logger

from .auth_password import parse_password_hash, verify_password

UserRole = Literal["admin", "user"]
SCHEMA_VERSION = 1


class AuthUserStoreUnavailableError(RuntimeError):
    """Raised when the persistent user store cannot be used safely."""


class UsernameConflictError(RuntimeError):
    """Raised when a normalized username already exists."""


class UserNotFoundError(RuntimeError):
    """Raised when a requested user no longer exists."""


class LastActiveAdminError(RuntimeError):
    """Raised when an operation would remove the last active administrator."""


@dataclass(frozen=True, slots=True)
class AuthUserHealth:
    available: bool
    reason: str | None

    def public_dict(self) -> dict[str, object | None]:
        return {
            "state": "ready" if self.available else "failed",
            "ready": self.available,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: str
    username: str
    password_hash: str
    role: UserRole
    enabled: bool
    must_change_password: bool
    credential_version: int
    created_at: int
    updated_at: int
    last_login_at: int | None
    created_by: str | None

    def public_dict(self, *, active_sessions: int | None = None) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "enabled": self.enabled,
            "must_change_password": self.must_change_password,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login_at": self.last_login_at,
        }
        if active_sessions is not None:
            result["active_sessions"] = active_sessions
        return result


class AuthUserStore:
    """Own the SQLite account database and its security audit trail."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        bootstrap_username: str,
        bootstrap_password_hash: str,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.db_path = Path(db_path) if str(db_path) != ":memory:" else Path(":memory:")
        self.bootstrap_username = bootstrap_username
        self.bootstrap_password_hash = bootstrap_password_hash
        self.busy_timeout_ms = busy_timeout_ms
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._health = AuthUserHealth(False, "not_started")

    @property
    def health(self) -> AuthUserHealth:
        return self._health

    async def start(self) -> AuthUserHealth:
        if self._db is not None:
            return self._health
        async with self._start_lock:
            if self._db is not None:
                return self._health
            try:
                if str(self.db_path) != ":memory:":
                    self.db_path.parent.mkdir(parents=True, exist_ok=True)
                parse_password_hash(self.bootstrap_password_hash)
                username, username_key = normalize_username(self.bootstrap_username)
                db = await aiosqlite.connect(str(self.db_path))
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA foreign_keys=ON")
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
                self._db = db
                await self._migrate(db)
                await self._bootstrap(db, username, username_key)
                self._health = AuthUserHealth(True, None)
            except Exception as exc:
                await self._discard_connection()
                self._mark_unavailable(exc, "start")
        return self._health

    async def check_health(self) -> AuthUserHealth:
        if self._db is None:
            return await self.start()
        try:
            await self._db.execute("SELECT 1")
            self._health = AuthUserHealth(True, None)
        except Exception as exc:
            self._mark_unavailable(exc, "health")
        return self._health

    async def authenticate(self, username: str, password: str) -> UserAccount | None:
        try:
            _, username_key = normalize_username(username)
        except ValueError:
            return None
        account = await self.get_by_username_key(username_key)
        if account is None or not verify_password(password, account.password_hash):
            return None
        return account

    async def get_by_id(self, user_id: str) -> UserAccount | None:
        db = await self._require_db()
        try:
            cursor = await db.execute("SELECT * FROM auth_users WHERE id=?", (user_id,))
            row = await cursor.fetchone()
        except Exception as exc:
            self._raise_unavailable(exc, "get_by_id")
        return _account_from_row(row) if row is not None else None

    async def get_by_username(self, username: str) -> UserAccount | None:
        try:
            _, username_key = normalize_username(username)
        except ValueError:
            return None
        return await self.get_by_username_key(username_key)

    async def get_by_username_key(self, username_key: str) -> UserAccount | None:
        db = await self._require_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM auth_users WHERE username_key=?",
                (username_key,),
            )
            row = await cursor.fetchone()
        except Exception as exc:
            self._raise_unavailable(exc, "get_by_username")
        return _account_from_row(row) if row is not None else None

    async def list_users(self) -> list[UserAccount]:
        db = await self._require_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM auth_users ORDER BY created_at ASC, username_key ASC"
            )
            rows = await cursor.fetchall()
        except Exception as exc:
            self._raise_unavailable(exc, "list")
        return [_account_from_row(row) for row in rows]

    async def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        role: UserRole,
        actor_user_id: str,
    ) -> UserAccount:
        display_name, username_key = normalize_username(username)
        parse_password_hash(password_hash)
        if role not in {"admin", "user"}:
            raise ValueError("invalid role")
        db = await self._require_db()
        user_id = uuid.uuid4().hex
        now = int(time.time())
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                await db.execute(
                    """
                    INSERT INTO auth_users(
                        id, username, username_key, password_hash, role, enabled,
                        must_change_password, credential_version, created_at,
                        updated_at, last_login_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, 1, 1, 1, ?, ?, NULL, ?)
                    """,
                    (
                        user_id,
                        display_name,
                        username_key,
                        password_hash,
                        role,
                        now,
                        now,
                        actor_user_id,
                    ),
                )
                await self._audit(db, actor_user_id, user_id, "account_created", now)
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                if "username_key" in str(exc).lower() or "unique" in str(exc).lower():
                    raise UsernameConflictError("USERNAME_CONFLICT") from exc
                self._raise_unavailable(exc, "create")
            except Exception as exc:
                await db.rollback()
                self._raise_unavailable(exc, "create")
        account = await self.get_by_id(user_id)
        if account is None:
            raise AuthUserStoreUnavailableError("created user is unavailable")
        return account

    async def record_login(self, user_id: str) -> UserAccount:
        return await self._update_timestamp(user_id, "last_login_at")

    async def update_password(
        self,
        user_id: str,
        *,
        password_hash: str,
        must_change_password: bool,
        actor_user_id: str,
        action: str,
        enable: bool | None = None,
    ) -> UserAccount:
        parse_password_hash(password_hash)
        db = await self._require_db()
        now = int(time.time())
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                row = await self._select_user(db, user_id)
                if row is None:
                    raise UserNotFoundError("USER_NOT_FOUND")
                enabled_sql = "enabled" if enable is None else "?"
                parameters: list[object] = [
                    password_hash,
                    int(must_change_password),
                    now,
                ]
                if enable is not None:
                    parameters.append(int(enable))
                parameters.append(user_id)
                await db.execute(
                    f"""
                    UPDATE auth_users SET password_hash=?, must_change_password=?,
                        updated_at=?, enabled={enabled_sql},
                        credential_version=credential_version+1
                    WHERE id=?
                    """,
                    tuple(parameters),
                )
                await self._audit(db, actor_user_id, user_id, action, now)
                await db.commit()
            except (UserNotFoundError, ValueError):
                await db.rollback()
                raise
            except Exception as exc:
                await db.rollback()
                self._raise_unavailable(exc, "update_password")
        account = await self.get_by_id(user_id)
        if account is None:
            raise UserNotFoundError("USER_NOT_FOUND")
        return account

    async def update_access(
        self,
        user_id: str,
        *,
        role: UserRole | None,
        enabled: bool | None,
        actor_user_id: str,
    ) -> tuple[UserAccount, bool]:
        if role is not None and role not in {"admin", "user"}:
            raise ValueError("invalid role")
        db = await self._require_db()
        now = int(time.time())
        changed = False
        async with self._lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                row = await self._select_user(db, user_id)
                if row is None:
                    raise UserNotFoundError("USER_NOT_FOUND")
                current = _account_from_row(row)
                next_role = role or current.role
                next_enabled = current.enabled if enabled is None else enabled
                changed = next_role != current.role or next_enabled != current.enabled
                removing_active_admin = (
                    current.role == "admin"
                    and current.enabled
                    and (next_role != "admin" or not next_enabled)
                )
                if removing_active_admin and await self._active_admin_count(db) <= 1:
                    raise LastActiveAdminError("LAST_ACTIVE_ADMIN")
                if changed:
                    await db.execute(
                        """
                        UPDATE auth_users SET role=?, enabled=?, updated_at=?,
                            credential_version=credential_version+1
                        WHERE id=?
                        """,
                        (next_role, int(next_enabled), now, user_id),
                    )
                    action = "account_access_changed"
                    await self._audit(db, actor_user_id, user_id, action, now)
                await db.commit()
            except (LastActiveAdminError, UserNotFoundError, ValueError):
                await db.rollback()
                raise
            except Exception as exc:
                await db.rollback()
                self._raise_unavailable(exc, "update_access")
        account = await self.get_by_id(user_id)
        if account is None:
            raise UserNotFoundError("USER_NOT_FOUND")
        return account, changed

    async def record_event(
        self,
        *,
        actor_user_id: str,
        target_user_id: str,
        action: str,
    ) -> None:
        db = await self._require_db()
        async with self._lock:
            try:
                await self._audit(db, actor_user_id, target_user_id, action, int(time.time()))
                await db.commit()
            except Exception as exc:
                with suppress(Exception):
                    await db.rollback()
                self._raise_unavailable(exc, "audit")

    async def close(self) -> None:
        await self._discard_connection()
        self._health = AuthUserHealth(False, "closed")

    async def _migrate(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        version = int(row[0]) if row is not None else 0
        if version > SCHEMA_VERSION:
            raise RuntimeError("auth database schema is newer than this runtime")
        if version == 0:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    username_key TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                    must_change_password INTEGER NOT NULL CHECK(must_change_password IN (0, 1)),
                    credential_version INTEGER NOT NULL CHECK(credential_version >= 1),
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    last_login_at INTEGER,
                    created_by TEXT REFERENCES auth_users(id)
                );
                CREATE INDEX IF NOT EXISTS ix_auth_users_role_enabled
                    ON auth_users(role, enabled);
                CREATE TABLE IF NOT EXISTS auth_audit_events (
                    id TEXT PRIMARY KEY,
                    actor_user_id TEXT,
                    target_user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_auth_audit_target_created
                    ON auth_audit_events(target_user_id, created_at);
                PRAGMA user_version=1;
                """
            )
            await db.commit()

    async def _bootstrap(
        self,
        db: aiosqlite.Connection,
        username: str,
        username_key: str,
    ) -> None:
        cursor = await db.execute("SELECT COUNT(*) FROM auth_users")
        row = await cursor.fetchone()
        if row is not None and int(row[0]) > 0:
            return
        user_id = uuid.uuid4().hex
        now = int(time.time())
        await db.execute(
            """
            INSERT INTO auth_users(
                id, username, username_key, password_hash, role, enabled,
                must_change_password, credential_version, created_at,
                updated_at, last_login_at, created_by
            ) VALUES (?, ?, ?, ?, 'admin', 1, 1, 1, ?, ?, NULL, NULL)
            """,
            (user_id, username, username_key, self.bootstrap_password_hash, now, now),
        )
        await self._audit(db, None, user_id, "bootstrap_admin_created", now)
        await db.commit()

    async def _update_timestamp(self, user_id: str, column: str) -> UserAccount:
        if column != "last_login_at":
            raise ValueError("unsupported timestamp column")
        db = await self._require_db()
        now = int(time.time())
        async with self._lock:
            try:
                cursor = await db.execute(
                    f"UPDATE auth_users SET {column}=?, updated_at=? WHERE id=?",
                    (now, now, user_id),
                )
                if cursor.rowcount == 0:
                    raise UserNotFoundError("USER_NOT_FOUND")
                await db.commit()
            except UserNotFoundError:
                raise
            except Exception as exc:
                with suppress(Exception):
                    await db.rollback()
                self._raise_unavailable(exc, "record_login")
        account = await self.get_by_id(user_id)
        if account is None:
            raise UserNotFoundError("USER_NOT_FOUND")
        return account

    async def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            health = await self.start()
            if not health.available or self._db is None:
                raise AuthUserStoreUnavailableError("user store is unavailable")
        return self._db

    async def _discard_connection(self) -> None:
        db, self._db = self._db, None
        if db is not None:
            with suppress(Exception):
                await db.close()

    @staticmethod
    async def _select_user(db: aiosqlite.Connection, user_id: str) -> aiosqlite.Row | None:
        cursor = await db.execute("SELECT * FROM auth_users WHERE id=?", (user_id,))
        return await cursor.fetchone()

    @staticmethod
    async def _active_admin_count(db: aiosqlite.Connection) -> int:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM auth_users WHERE role='admin' AND enabled=1"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row is not None else 0

    @staticmethod
    async def _audit(
        db: aiosqlite.Connection,
        actor_user_id: str | None,
        target_user_id: str,
        action: str,
        created_at: int,
    ) -> None:
        await db.execute(
            """
            INSERT INTO auth_audit_events(id, actor_user_id, target_user_id, action, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex, actor_user_id, target_user_id, action, created_at),
        )

    def _raise_unavailable(self, exc: Exception, operation: str) -> None:
        self._mark_unavailable(exc, operation)
        raise AuthUserStoreUnavailableError("user store is unavailable") from exc

    def _mark_unavailable(self, exc: Exception, operation: str) -> None:
        self._health = AuthUserHealth(False, "auth_user_unavailable")
        logger.warning(
            "[AuthUser] SQLite {} failed: error_type={}",
            operation,
            type(exc).__name__,
        )


def normalize_username(value: str) -> tuple[str, str]:
    """Return display and case-insensitive identity forms for a username."""
    display = unicodedata.normalize("NFKC", value.strip())
    if not 1 <= len(display) <= 64:
        raise ValueError("username must contain between 1 and 64 characters")
    if any(unicodedata.category(character).startswith("C") for character in display):
        raise ValueError("username contains a control character")
    return display, display.casefold()


def _account_from_row(row: aiosqlite.Row) -> UserAccount:
    return UserAccount(
        id=str(row["id"]),
        username=str(row["username"]),
        password_hash=str(row["password_hash"]),
        role=str(row["role"]),  # type: ignore[arg-type]
        enabled=bool(row["enabled"]),
        must_change_password=bool(row["must_change_password"]),
        credential_version=int(row["credential_version"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        last_login_at=int(row["last_login_at"]) if row["last_login_at"] is not None else None,
        created_by=str(row["created_by"]) if row["created_by"] is not None else None,
    )
