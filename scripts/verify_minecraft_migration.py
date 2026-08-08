"""Verify additive control-plane migration on a backed-up skill database copy."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from animetta.tools.minecraft.skill.revision_store import SkillRevisionStore
from animetta.tools.minecraft.voyager.sqlite_repository import SQLiteCommandJournal


async def verify_migration_copy(source_skill_db: Path, *, evidence_dir: Path) -> dict[str, object]:
    if not source_skill_db.is_file():
        raise FileNotFoundError(source_skill_db)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    backup = evidence_dir / "skills.before.db"
    migrated = evidence_dir / "skills.migrated.db"
    shutil.copy2(source_skill_db, backup)
    shutil.copy2(backup, migrated)

    store = SkillRevisionStore(migrated)
    await store.connect()
    try:
        migrated_count = await store.migrate_legacy_skills()
        records = await store.legacy_migrations()
    finally:
        await store.close()

    journal_path = evidence_dir / "commands.db"
    journal = SQLiteCommandJournal(journal_path)
    await journal.connect()
    try:
        pragmas = await journal.pragmas()
        indexes = sorted(await journal.index_names())
    finally:
        await journal.close()

    statuses = sorted({record["migration_status"] for record in records})
    if statuses not in ([], ["legacy_untrusted"]):
        raise RuntimeError(f"legacy trust was inherited unexpectedly: {statuses}")
    return {
        "source": str(source_skill_db),
        "backup": str(backup),
        "migrated_copy": str(migrated),
        "migrated_count": migrated_count,
        "legacy_statuses": statuses,
        "journal_mode": pragmas["journal_mode"],
        "indexes": indexes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_skill_db", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(
        verify_migration_copy(args.source_skill_db, evidence_dir=args.evidence_dir)
    )
    output = args.evidence_dir / "migration-report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
