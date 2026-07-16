"""SQLite persistence for Minecraft skills."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from .models import Skill, SkillProvenance, SkillStep, SkillTrustStage

if TYPE_CHECKING:
    import aiosqlite

_SKILLS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    parameters_json TEXT DEFAULT '{}',
    preconditions_json TEXT DEFAULT '[]',
    body_json TEXT DEFAULT '{}',
    steps_json TEXT DEFAULT '[]',
    category TEXT DEFAULT '',
    postconditions_json TEXT DEFAULT '[]',
    success_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    avg_duration REAL DEFAULT 0.0,
    last_used TEXT DEFAULT '',
    tags_json TEXT DEFAULT '[]',
    is_learned INTEGER DEFAULT 0,
    validated INTEGER DEFAULT 1,
    trust_stage TEXT DEFAULT 'candidate',
    provenance_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


class SkillLibraryDB:
    """Async SQLite persistence for SkillLibrary."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open connection and create table if needed."""
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(_SKILLS_TABLE_SQL)
        cursor = await self._db.execute("PRAGMA table_info(skills)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "trust_stage" not in columns:
            await self._db.execute(
                "ALTER TABLE skills ADD COLUMN trust_stage TEXT DEFAULT 'candidate'"
            )
        if "provenance_json" not in columns:
            await self._db.execute(
                "ALTER TABLE skills ADD COLUMN provenance_json TEXT DEFAULT '{}'"
            )
        if "consecutive_failures" not in columns:
            await self._db.execute(
                "ALTER TABLE skills ADD COLUMN consecutive_failures INTEGER DEFAULT 0"
            )
        await self._db.commit()
        logger.info(f"[SkillLibraryDB] Connected to {self._db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def load_all(self) -> dict[str, Skill]:
        """Load all skills from SQLite into a dict."""
        if not self._db:
            return {}
        cursor = await self._db.execute("SELECT * FROM skills")
        rows = await cursor.fetchall()
        skills: dict[str, Skill] = {}
        for row in rows:
            skill = self._row_to_skill(row)
            skills[skill.id] = skill
        logger.info(f"[SkillLibraryDB] Loaded {len(skills)} skills from SQLite")
        return skills

    async def save_skill(self, skill: Skill) -> None:
        """Insert or replace a skill in SQLite."""
        if not self._db:
            return
        await self._db.execute(
            """INSERT OR REPLACE INTO skills
            (id, name, description, parameters_json, preconditions_json,
             body_json, steps_json, category, postconditions_json,
             success_count, fail_count, consecutive_failures, avg_duration, last_used,
             tags_json, is_learned, validated, trust_stage, provenance_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self._skill_to_row(skill),
        )
        await self._db.commit()

    async def update_stats(
        self,
        skill_id: str,
        success_count: int,
        fail_count: int,
        consecutive_failures: int,
        avg_duration: float,
        last_used: str,
    ) -> None:
        """Update only the stats columns for a skill."""
        if not self._db:
            return
        await self._db.execute(
            """UPDATE skills SET success_count=?, fail_count=?, consecutive_failures=?,
            avg_duration=?, last_used=? WHERE id=?""",
            (
                success_count,
                fail_count,
                consecutive_failures,
                avg_duration,
                last_used,
                skill_id,
            ),
        )
        await self._db.commit()

    async def delete_skill(self, skill_id: str) -> None:
        """Delete a skill from SQLite."""
        if not self._db:
            return
        await self._db.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        await self._db.commit()

    def _skill_to_row(self, skill: Skill) -> tuple:
        """Convert a Skill to a SQLite row tuple."""
        return (
            skill.id,
            skill.name,
            skill.description,
            json.dumps(skill.parameters, ensure_ascii=False),
            json.dumps(skill.preconditions, ensure_ascii=False),
            json.dumps(skill.body, ensure_ascii=False),
            json.dumps([s.to_dict() for s in skill.steps], ensure_ascii=False),
            skill.category,
            json.dumps(skill.postconditions, ensure_ascii=False),
            skill.success_count,
            skill.fail_count,
            skill.consecutive_failures,
            skill.avg_duration,
            skill.last_used,
            json.dumps(skill.tags, ensure_ascii=False),
            int(skill.is_learned),
            int(skill.validated),
            skill.trust_stage.value,
            json.dumps(skill.provenance.to_dict(), ensure_ascii=False),
        )

    def _row_to_skill(self, row: aiosqlite.Row) -> Skill:
        """Convert a SQLite row to a Skill."""
        return Skill(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            parameters=json.loads(row["parameters_json"] or "{}"),
            preconditions=json.loads(row["preconditions_json"] or "[]"),
            body=json.loads(row["body_json"] or "{}"),
            steps=[SkillStep.from_dict(s) for s in json.loads(row["steps_json"] or "[]")],
            category=row["category"] or "",
            postconditions=json.loads(row["postconditions_json"] or "[]"),
            success_count=row["success_count"],
            fail_count=row["fail_count"],
            consecutive_failures=row["consecutive_failures"],
            avg_duration=row["avg_duration"],
            last_used=row["last_used"] or "",
            tags=json.loads(row["tags_json"] or "[]"),
            is_learned=bool(row["is_learned"]),
            validated=bool(row["validated"]),
            trust_stage=SkillTrustStage(row["trust_stage"] or "candidate"),
            provenance=SkillProvenance.from_dict(json.loads(row["provenance_json"] or "{}")),
        )
