"""Additive SQLite persistence and offline conversion for immutable skill revisions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash

from .applicability import SkillApplicability
from .independent_validation import (
    IndependentValidationEvidence,
    decide_independent_validation,
    goal_contract_hash,
)
from .ir import SkillDefinition, SkillProgram, SkillRevision
from .trust import (
    ExecutionAttribution,
    SkillEnvironmentTrust,
    TrustStatus,
    apply_execution_outcome,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_schema_meta (
    schema_version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skill_definitions (
    definition_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skill_revisions (
    revision_hash TEXT PRIMARY KEY,
    definition_id TEXT NOT NULL,
    parent_revision_hash TEXT,
    program_json TEXT,
    static_cost_json TEXT,
    legacy_payload_json TEXT,
    source_command_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(definition_id) REFERENCES skill_definitions(definition_id)
);
CREATE TABLE IF NOT EXISTS skill_environment_validations (
    revision_hash TEXT NOT NULL,
    environment_fingerprint TEXT NOT NULL,
    trust_status TEXT NOT NULL,
    policy_report_json TEXT NOT NULL DEFAULT '{}',
    learning_evidence_json TEXT NOT NULL DEFAULT '[]',
    validation_evidence_json TEXT NOT NULL DEFAULT '[]',
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    expected_cost REAL NOT NULL DEFAULT 0,
    portable INTEGER NOT NULL DEFAULT 0,
    revision_quarantined INTEGER NOT NULL DEFAULT 0,
    demotion_reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(revision_hash, environment_fingerprint)
);
CREATE TABLE IF NOT EXISTS skill_execution_records (
    execution_id TEXT PRIMARY KEY,
    revision_hash TEXT NOT NULL,
    environment_fingerprint TEXT NOT NULL,
    attribution TEXT NOT NULL,
    command_id TEXT NOT NULL,
    receipt_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skill_demotion_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_hash TEXT NOT NULL,
    environment_fingerprint TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skill_revision_quarantine (
    revision_hash TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    source_execution_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS skill_applicability (
    revision_hash TEXT PRIMARY KEY,
    applicability_hash TEXT NOT NULL UNIQUE,
    applicability_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(revision_hash) REFERENCES skill_revisions(revision_hash)
);
CREATE TABLE IF NOT EXISTS skill_independent_validations (
    validation_id TEXT PRIMARY KEY,
    revision_hash TEXT NOT NULL,
    environment_fingerprint TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    trust_status TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    policy_report_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(revision_hash) REFERENCES skill_revisions(revision_hash)
);
CREATE TABLE IF NOT EXISTS legacy_skill_migrations (
    legacy_skill_id TEXT PRIMARY KEY,
    revision_hash TEXT NOT NULL,
    migration_status TEXT NOT NULL,
    legacy_validated INTEGER NOT NULL,
    legacy_learned INTEGER NOT NULL,
    migrated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_skill_revisions_definition
ON skill_revisions(definition_id, created_at);
CREATE INDEX IF NOT EXISTS idx_skill_validation_environment
ON skill_environment_validations(environment_fingerprint, trust_status);
"""


@dataclass(frozen=True)
class LegacySkillCandidate:
    legacy_skill_id: str
    program: SkillProgram
    trust_status: TrustStatus = TrustStatus.CANDIDATE


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return normalized[:128] or "legacy_skill"


def convert_legacy_skill(payload: dict[str, Any]) -> LegacySkillCandidate | None:
    """Convert legacy plan steps offline; never carry legacy validation into trust."""

    steps = payload.get("steps") or []
    if not steps:
        return None
    converted = []
    for index, step in enumerate(steps, start=1):
        capability = step.get("name") or step.get("action")
        if not isinstance(capability, str):
            return None
        params = step.get("params") or {}
        if not isinstance(params, dict):
            return None
        converted.append(
            {
                "kind": "action",
                "step_id": f"legacy-{index}",
                "capability": capability,
                "parameters": {
                    name: {"kind": "literal", "value": value}
                    for name, value in params.items()
                    if isinstance(value, (str, int, float, bool)) or value is None
                },
            }
        )
    program = SkillProgram.model_validate(
        {
            "name": _safe_name(str(payload.get("id") or payload.get("name") or "legacy")),
            "steps": converted,
            "postconditions": [
                {
                    "op": "gte",
                    "left": {"kind": "observation", "path": "health"},
                    "right": {"kind": "literal", "value": 0},
                }
            ],
            "portability": {"portable": False},
        }
    )
    return LegacySkillCandidate(
        legacy_skill_id=str(payload.get("id", program.name)), program=program
    )


class SkillRevisionStore:
    SCHEMA_VERSION = 3

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: Any = None

    async def connect(self) -> None:
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.executescript(_SCHEMA)
        columns = await self._db.execute("PRAGMA table_info(skill_revisions)")
        if "static_cost_json" not in {row[1] for row in await columns.fetchall()}:
            await self._db.execute("ALTER TABLE skill_revisions ADD COLUMN static_cost_json TEXT")
        validation_columns = await self._db.execute(
            "PRAGMA table_info(skill_environment_validations)"
        )
        existing_validation = {row[1] for row in await validation_columns.fetchall()}
        for name, definition in {
            "expected_cost": "REAL NOT NULL DEFAULT 0",
            "portable": "INTEGER NOT NULL DEFAULT 0",
            "revision_quarantined": "INTEGER NOT NULL DEFAULT 0",
            "demotion_reason": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in existing_validation:
                await self._db.execute(
                    f"ALTER TABLE skill_environment_validations ADD COLUMN {name} {definition}"
                )
        await self._db.execute(
            "INSERT OR IGNORE INTO skill_schema_meta(schema_version) VALUES (?)",
            (self.SCHEMA_VERSION,),
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def migrate_legacy_skills(self) -> int:
        if self._db is None:
            raise RuntimeError("store is not connected")
        table = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='skills'"
        )
        if await table.fetchone() is None:
            return 0
        cursor = await self._db.execute("SELECT * FROM skills ORDER BY id")
        migrated = 0
        for row in await cursor.fetchall():
            payload = dict(row)
            legacy_id = str(payload["id"])
            body = json.loads(payload.get("body_json") or "{}")
            steps = json.loads(payload.get("steps_json") or "[]")
            legacy_payload = {
                "id": legacy_id,
                "name": payload.get("name") or legacy_id,
                "description": payload.get("description") or "",
                "body": body,
                "steps": steps,
            }
            revision_hash = canonical_json_hash(legacy_payload)
            await self._db.execute(
                """INSERT OR IGNORE INTO skill_definitions
                (definition_id, name, description) VALUES (?, ?, ?)""",
                (legacy_id, legacy_payload["name"], legacy_payload["description"]),
            )
            await self._db.execute(
                """INSERT OR IGNORE INTO skill_revisions
                (revision_hash, definition_id, legacy_payload_json)
                VALUES (?, ?, ?)""",
                (
                    revision_hash,
                    legacy_id,
                    json.dumps(legacy_payload, sort_keys=True, ensure_ascii=False),
                ),
            )
            before = self._db.total_changes
            await self._db.execute(
                """INSERT OR IGNORE INTO legacy_skill_migrations
                (legacy_skill_id, revision_hash, migration_status,
                 legacy_validated, legacy_learned)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    legacy_id,
                    revision_hash,
                    TrustStatus.LEGACY_UNTRUSTED.value,
                    int(payload.get("validated") or 0),
                    int(payload.get("is_learned") or 0),
                ),
            )
            if self._db.total_changes > before:
                migrated += 1
        await self._db.commit()
        return migrated

    async def legacy_migrations(self) -> list[dict[str, Any]]:
        if self._db is None:
            raise RuntimeError("store is not connected")
        cursor = await self._db.execute(
            "SELECT * FROM legacy_skill_migrations ORDER BY legacy_skill_id"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def save_revision(self, definition: SkillDefinition, revision: SkillRevision) -> None:
        """Persist one immutable revision without overwriting prior history."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        await self._db.execute(
            """INSERT OR IGNORE INTO skill_definitions
            (definition_id, name, description) VALUES (?, ?, ?)""",
            (definition.definition_id, definition.name, definition.description),
        )
        await self._db.execute(
            """INSERT OR IGNORE INTO skill_revisions
            (revision_hash, definition_id, parent_revision_hash, program_json,
             static_cost_json, source_command_id)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                revision.revision_hash,
                revision.definition_id,
                revision.parent_revision_hash,
                revision.program.model_dump_json(),
                revision.static_cost.model_dump_json(),
                revision.source_command_id,
            ),
        )
        await self._db.commit()

    async def save_applicability(self, applicability: SkillApplicability) -> None:
        """Persist one immutable applicability declaration beside its revision."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        revision_cursor = await self._db.execute(
            "SELECT 1 FROM skill_revisions WHERE revision_hash=? AND program_json IS NOT NULL",
            (applicability.revision_hash,),
        )
        if await revision_cursor.fetchone() is None:
            raise ValueError("UNKNOWN_SKILL_REVISION")
        payload = json.dumps(
            applicability.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        existing_cursor = await self._db.execute(
            """SELECT applicability_hash,applicability_json
            FROM skill_applicability WHERE revision_hash=?""",
            (applicability.revision_hash,),
        )
        existing = await existing_cursor.fetchone()
        if existing is not None:
            if (
                existing["applicability_hash"] != applicability.applicability_hash
                or existing["applicability_json"] != payload
            ):
                raise ValueError("IMMUTABLE_APPLICABILITY_CONFLICT")
            return
        await self._db.execute(
            """INSERT INTO skill_applicability
            (revision_hash,applicability_hash,applicability_json)
            VALUES (?,?,?)""",
            (
                applicability.revision_hash,
                applicability.applicability_hash,
                payload,
            ),
        )
        await self._db.commit()

    async def load_applicability(self, revision_hash: str) -> SkillApplicability | None:
        """Load and hash-check the immutable applicability for one revision."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        cursor = await self._db.execute(
            """SELECT applicability_hash,applicability_json
            FROM skill_applicability WHERE revision_hash=?""",
            (revision_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        applicability = SkillApplicability.model_validate(json.loads(row["applicability_json"]))
        if applicability.applicability_hash != row["applicability_hash"]:
            raise ValueError("APPLICABILITY_HASH_MISMATCH")
        return applicability

    async def load_applicabilities(self) -> dict[str, SkillApplicability]:
        """Load and hash-check every immutable applicability declaration."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        cursor = await self._db.execute(
            """SELECT revision_hash,applicability_hash,applicability_json
            FROM skill_applicability ORDER BY revision_hash"""
        )
        result: dict[str, SkillApplicability] = {}
        for row in await cursor.fetchall():
            applicability = SkillApplicability.model_validate(json.loads(row["applicability_json"]))
            if applicability.applicability_hash != row["applicability_hash"]:
                raise ValueError("APPLICABILITY_HASH_MISMATCH")
            result[row["revision_hash"]] = applicability
        return result

    async def record_validation(
        self,
        trust: SkillEnvironmentTrust,
        *,
        policy_report: dict[str, Any],
        learning_evidence: tuple[str, ...],
        validation_evidence: tuple[str, ...],
    ) -> None:
        """Upsert environment-scoped validation while retaining evidence chains."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        await self._db.execute(
            """INSERT INTO skill_environment_validations
            (revision_hash, environment_fingerprint, trust_status,
             policy_report_json, learning_evidence_json, validation_evidence_json,
             successes, failures, consecutive_failures, expected_cost, portable,
             revision_quarantined, demotion_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(revision_hash, environment_fingerprint) DO UPDATE SET
              trust_status=excluded.trust_status,
              policy_report_json=excluded.policy_report_json,
              learning_evidence_json=excluded.learning_evidence_json,
              validation_evidence_json=excluded.validation_evidence_json,
              successes=excluded.successes,
              failures=excluded.failures,
              consecutive_failures=excluded.consecutive_failures,
              expected_cost=excluded.expected_cost,
              portable=excluded.portable,
              revision_quarantined=excluded.revision_quarantined,
              demotion_reason=excluded.demotion_reason""",
            (
                trust.revision_hash,
                trust.environment_fingerprint,
                trust.status.value,
                json.dumps(policy_report, sort_keys=True),
                json.dumps(learning_evidence),
                json.dumps(validation_evidence),
                trust.successes,
                trust.failures,
                trust.consecutive_failures,
                trust.expected_cost,
                int(trust.portable),
                int(trust.revision_quarantined),
                trust.demotion_reason,
            ),
        )
        await self._db.commit()

    async def record_independent_validation(
        self,
        evidence: IndependentValidationEvidence,
        *,
        policy_report: dict[str, Any],
        expected_cost: float,
        portable: bool,
    ) -> SkillEnvironmentTrust:
        """Persist one independent decision and expose only its resulting trust."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        revision_cursor = await self._db.execute(
            """SELECT program_json FROM skill_revisions
            WHERE revision_hash=? AND program_json IS NOT NULL""",
            (evidence.revision_hash,),
        )
        revision_row = await revision_cursor.fetchone()
        if revision_row is None:
            raise ValueError("UNKNOWN_SKILL_REVISION")
        revision_program = SkillProgram.model_validate(json.loads(revision_row["program_json"]))
        decision = decide_independent_validation(
            evidence,
            expected_goal_contract_hash=goal_contract_hash(revision_program.postconditions),
        )
        evidence_json = json.dumps(
            evidence.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        policy_json = json.dumps(policy_report, sort_keys=True, separators=(",", ":"))
        existing_cursor = await self._db.execute(
            """SELECT evidence_json,trust_status,reason_code,policy_report_json
            FROM skill_independent_validations WHERE validation_id=?""",
            (evidence.validation_id,),
        )
        existing = await existing_cursor.fetchone()
        values = (
            evidence_json,
            decision.trust_status,
            decision.reason_code,
            policy_json,
        )
        if existing is not None and tuple(existing) != values:
            raise ValueError("IMMUTABLE_VALIDATION_CONFLICT")
        if existing is None:
            await self._db.execute(
                """INSERT INTO skill_independent_validations
                (validation_id,revision_hash,environment_fingerprint,evidence_json,
                 trust_status,reason_code,policy_report_json)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    evidence.validation_id,
                    evidence.revision_hash,
                    evidence.environment_fingerprint,
                    *values,
                ),
            )
            await self._db.commit()
        trust = SkillEnvironmentTrust(
            revision_hash=evidence.revision_hash,
            environment_fingerprint=evidence.environment_fingerprint,
            status=TrustStatus(decision.trust_status),
            successes=int(decision.trust_status == "trusted"),
            failures=int(not evidence.goal_verified),
            expected_cost=expected_cost,
            portable=portable,
        )
        await self.record_validation(
            trust,
            policy_report={**policy_report, "validation_reason": decision.reason_code},
            learning_evidence=evidence.learning.receipt_refs,
            validation_evidence=evidence.validation.receipt_refs,
        )
        return trust

    async def load_live_catalog(
        self, *, environment_fingerprint: str
    ) -> tuple[dict[str, SkillRevision], list[SkillEnvironmentTrust]]:
        """Load declarative revisions and matching trust without executable legacy rows."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        cursor = await self._db.execute(
            """SELECT revision_hash, definition_id, parent_revision_hash,
                      program_json, static_cost_json, source_command_id
               FROM skill_revisions
               WHERE program_json IS NOT NULL AND static_cost_json IS NOT NULL
               ORDER BY revision_hash"""
        )
        revisions: dict[str, SkillRevision] = {}
        for row in await cursor.fetchall():
            revision = SkillRevision.model_validate(
                {
                    "revision_hash": row["revision_hash"],
                    "definition_id": row["definition_id"],
                    "parent_revision_hash": row["parent_revision_hash"],
                    "program": json.loads(row["program_json"]),
                    "static_cost": json.loads(row["static_cost_json"]),
                    "source_command_id": row["source_command_id"],
                }
            )
            revisions[revision.revision_hash] = revision
        trust_cursor = await self._db.execute(
            """SELECT revision_hash, environment_fingerprint, trust_status,
                      successes, failures, consecutive_failures, expected_cost,
                      portable, revision_quarantined, demotion_reason
               FROM skill_environment_validations
               WHERE environment_fingerprint = ?
               ORDER BY revision_hash""",
            (environment_fingerprint,),
        )
        trusts = [
            SkillEnvironmentTrust(
                revision_hash=row["revision_hash"],
                environment_fingerprint=row["environment_fingerprint"],
                status=TrustStatus(row["trust_status"]),
                successes=row["successes"],
                failures=row["failures"],
                consecutive_failures=row["consecutive_failures"],
                expected_cost=row["expected_cost"],
                portable=bool(row["portable"]),
                revision_quarantined=bool(row["revision_quarantined"]),
                demotion_reason=row["demotion_reason"],
            )
            for row in await trust_cursor.fetchall()
        ]
        return revisions, trusts

    async def load_independent_validation_evidence(
        self,
        *,
        revision_hash: str,
        environment_fingerprint: str,
    ) -> tuple[IndependentValidationEvidence, ...]:
        """Load immutable source-A/source-B proof for presentation and audit."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        cursor = await self._db.execute(
            """SELECT evidence_json
               FROM skill_independent_validations
               WHERE revision_hash=? AND environment_fingerprint=?
               ORDER BY validation_id""",
            (revision_hash, environment_fingerprint),
        )
        return tuple(
            IndependentValidationEvidence.model_validate(json.loads(row["evidence_json"]))
            for row in await cursor.fetchall()
        )

    async def record_execution_outcome(
        self,
        *,
        execution_id: str,
        trust: SkillEnvironmentTrust,
        attribution: ExecutionAttribution,
        command_id: str,
        receipt_refs: tuple[str, ...] = (),
        demotion_threshold: int = 3,
    ) -> SkillEnvironmentTrust:
        """Atomically retain execution evidence and update scoped trust."""

        if self._db is None:
            raise RuntimeError("store is not connected")
        updated = apply_execution_outcome(trust, attribution, demotion_threshold=demotion_threshold)
        await self._db.execute("BEGIN IMMEDIATE")
        try:
            await self._db.execute(
                """INSERT INTO skill_execution_records
                (execution_id, revision_hash, environment_fingerprint,
                 attribution, command_id, receipt_refs_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    execution_id,
                    trust.revision_hash,
                    trust.environment_fingerprint,
                    attribution.value,
                    command_id,
                    json.dumps(receipt_refs),
                ),
            )
            await self._db.execute(
                """UPDATE skill_environment_validations SET
                trust_status=?, successes=?, failures=?, consecutive_failures=?,
                expected_cost=?, portable=?, revision_quarantined=?, demotion_reason=?
                WHERE revision_hash=? AND environment_fingerprint=?""",
                (
                    updated.status.value,
                    updated.successes,
                    updated.failures,
                    updated.consecutive_failures,
                    updated.expected_cost,
                    int(updated.portable),
                    int(updated.revision_quarantined),
                    updated.demotion_reason,
                    updated.revision_hash,
                    updated.environment_fingerprint,
                ),
            )
            if updated.status is TrustStatus.DEMOTED and trust.status is not TrustStatus.DEMOTED:
                await self._db.execute(
                    """INSERT INTO skill_demotion_history
                    (revision_hash, environment_fingerprint, reason)
                    VALUES (?, ?, ?)""",
                    (
                        updated.revision_hash,
                        updated.environment_fingerprint,
                        updated.demotion_reason,
                    ),
                )
            if updated.revision_quarantined:
                await self._db.execute(
                    """INSERT OR IGNORE INTO skill_revision_quarantine
                    (revision_hash, reason, source_execution_id) VALUES (?, ?, ?)""",
                    (
                        updated.revision_hash,
                        updated.demotion_reason,
                        execution_id,
                    ),
                )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise
        return updated
