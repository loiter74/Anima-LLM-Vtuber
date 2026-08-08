"""Migration verification never mutates the source representative database."""

from __future__ import annotations

import sqlite3

from scripts.verify_minecraft_migration import verify_migration_copy


async def test_representative_database_is_backed_up_and_legacy_trust_is_not_inherited(
    tmp_path,
) -> None:
    source = tmp_path / "mc_skills.db"
    connection = sqlite3.connect(source)
    connection.execute(
        """CREATE TABLE skills (
        id TEXT PRIMARY KEY, name TEXT, description TEXT, body_json TEXT,
        steps_json TEXT, is_learned INTEGER, validated INTEGER,
        success_count INTEGER, fail_count INTEGER)"""
    )
    connection.execute(
        "INSERT INTO skills VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "legacy-code",
            "Legacy code",
            "",
            '{"type":"code","code":"await collect()"}',
            "[]",
            1,
            1,
            9,
            0,
        ),
    )
    connection.commit()
    connection.close()
    source_bytes = source.read_bytes()

    report = await verify_migration_copy(source, evidence_dir=tmp_path / "evidence")

    assert source.read_bytes() == source_bytes
    assert report["legacy_statuses"] == ["legacy_untrusted"]
    assert (tmp_path / "evidence" / "skills.before.db").is_file()
    assert report["journal_mode"] == "wal"
