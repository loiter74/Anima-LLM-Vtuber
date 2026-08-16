from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from animetta.orchestration.server.auth_admin_cli import reset_admin_password
from animetta.orchestration.server.auth_password import hash_password
from animetta.orchestration.server.auth_user import (
    AuthUserStore,
    LastActiveAdminError,
    UsernameConflictError,
    normalize_username,
)


async def test_bootstrap_credentials_only_seed_an_empty_database(tmp_path: Path) -> None:
    database = tmp_path / "auth.db"
    first_hash = hash_password("first-password")
    store = AuthUserStore(
        database,
        bootstrap_username="Admin",
        bootstrap_password_hash=first_hash,
    )
    assert (await store.start()).available is True
    first = await store.authenticate("admin", "first-password")
    assert first is not None
    assert first.role == "admin"
    assert first.must_change_password is True
    await store.close()

    replacement = AuthUserStore(
        database,
        bootstrap_username="replacement",
        bootstrap_password_hash=hash_password("replacement-password"),
    )
    assert (await replacement.start()).available is True
    assert await replacement.authenticate("ADMIN", "first-password") is not None
    assert await replacement.authenticate("replacement", "replacement-password") is None
    await replacement.close()


async def test_username_normalization_conflicts_and_last_admin_are_enforced() -> None:
    store = AuthUserStore(
        ":memory:",
        bootstrap_username="Ａｄｍｉｎ",
        bootstrap_password_hash=hash_password("admin-password"),
    )
    assert (await store.start()).available is True
    admin = await store.authenticate("admin", "admin-password")
    assert admin is not None
    with pytest.raises(UsernameConflictError):
        await store.create_user(
            username=" ADMIN ",
            password_hash=hash_password("another-password"),
            role="user",
            actor_user_id=admin.id,
        )
    with pytest.raises(LastActiveAdminError):
        await store.update_access(
            admin.id,
            role="user",
            enabled=None,
            actor_user_id=admin.id,
        )
    await store.close()


@pytest.mark.parametrize("username", ["", " " * 3, "a" * 65, "name\u0000"])
def test_invalid_username_is_rejected(username: str) -> None:
    with pytest.raises(ValueError):
        normalize_username(username)


async def test_password_updates_increment_version_and_audit_without_secrets(tmp_path: Path) -> None:
    database = tmp_path / "auth.db"
    store = AuthUserStore(
        database,
        bootstrap_username="admin",
        bootstrap_password_hash=hash_password("admin-password"),
    )
    await store.start()
    admin = await store.authenticate("admin", "admin-password")
    assert admin is not None
    updated = await store.update_password(
        admin.id,
        password_hash=hash_password("updated-password"),
        must_change_password=False,
        actor_user_id=admin.id,
        action="password_changed",
    )
    assert updated.credential_version == admin.credential_version + 1
    assert updated.must_change_password is False
    await store.close()

    database_connection = await aiosqlite.connect(database)
    cursor = await database_connection.execute(
        "SELECT action FROM auth_audit_events ORDER BY created_at, rowid"
    )
    actions = [row[0] for row in await cursor.fetchall()]
    await database_connection.close()
    assert actions == ["bootstrap_admin_created", "password_changed"]
    assert "admin-password" not in database.read_bytes().decode("utf-8", errors="ignore")
    assert "updated-password" not in database.read_bytes().decode("utf-8", errors="ignore")


async def test_local_admin_reset_reads_secret_from_memory_and_forces_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bootstrap_hash = hash_password("admin-password")
    monkeypatch.setenv("ANIMETTA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANIMETTA_AUTH_USERNAME", "admin")
    monkeypatch.setenv("ANIMETTA_AUTH_PASSWORD_HASH", bootstrap_hash)
    monkeypatch.delenv("ANIMETTA_REDIS_URL", raising=False)

    assert await reset_admin_password("admin", enable=False, password="recovered-password") == 0
    output = capsys.readouterr().out
    assert "recovered-password" not in output
    assert '"password_change_required": true' in output

    store = AuthUserStore(
        tmp_path / "auth.db",
        bootstrap_username="ignored",
        bootstrap_password_hash=hash_password("ignored-password"),
    )
    await store.start()
    account = await store.authenticate("admin", "recovered-password")
    assert account is not None
    assert account.must_change_password is True
    await store.close()
