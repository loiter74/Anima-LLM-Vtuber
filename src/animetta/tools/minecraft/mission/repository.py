"""Repository protocols and additive persistence for adaptive missions."""

from __future__ import annotations

import asyncio
import json
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from animetta.tools.minecraft.voyager.budget import BudgetAccount

from .models import (
    GoalAdmissionDecision,
    GoalProposal,
    MissionObjective,
    MissionSpec,
)


class MissionIdempotencyConflictError(ValueError):
    """One caller reused a request ID for a different immutable mission."""


class MissionStatus(StrEnum):
    ACCEPTED = "accepted"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_EVIDENCE = "waiting_evidence"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED_UNKNOWN = "blocked_unknown"


class ObjectiveStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    BLOCKED_UNKNOWN = "blocked_unknown"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MissionRecord(_FrozenModel):
    caller_scope: str
    request_id: str
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    spec: MissionSpec
    status: MissionStatus = MissionStatus.ACCEPTED
    version: int = Field(default=0, ge=0)
    created_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)


class ObjectiveRecord(_FrozenModel):
    mission_id: str
    ordinal: int = Field(ge=0)
    objective: MissionObjective
    status: ObjectiveStatus = ObjectiveStatus.PENDING
    version: int = Field(default=0, ge=0)


class MissionTransitionDraft(_FrozenModel):
    mission_id: str
    objective_id: str | None = None
    entity_version: int = Field(ge=0)
    from_state: str | None = None
    to_state: str
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    actor: str = Field(min_length=1, max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    occurred_at_ms: int = Field(ge=0)


class MissionTransitionRecord(MissionTransitionDraft):
    transition_id: int = Field(gt=0)


class StoredGoalProposal(_FrozenModel):
    proposal: GoalProposal
    decision: GoalAdmissionDecision
    occurred_at_ms: int = Field(ge=0)


class MissionEvidenceLink(_FrozenModel):
    link_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    mission_id: str
    objective_id: str | None = None
    evidence_kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    evidence_ref: str = Field(min_length=1, max_length=512)
    command_id: str | None = None
    attributable: bool
    linked_at_ms: int = Field(ge=0)


class PresentationArtifact(_FrozenModel):
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    mission_id: str
    stage_id: str
    artifact_kind: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at_ms: int = Field(ge=0)
    sanitized: bool

    @field_validator("path")
    @classmethod
    def _repository_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("artifact path must be repository-relative")
        return path.as_posix()


class MissionSnapshot(_FrozenModel):
    mission: MissionRecord
    objectives: tuple[ObjectiveRecord, ...]
    transitions: tuple[MissionTransitionRecord, ...]
    proposals: tuple[StoredGoalProposal, ...]
    budget: BudgetAccount | None = None
    evidence_links: tuple[MissionEvidenceLink, ...] = ()
    presentation_artifacts: tuple[PresentationArtifact, ...] = ()


class MissionRepository(Protocol):
    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def create_mission(
        self,
        *,
        caller_scope: str,
        request_id: str,
        spec: MissionSpec,
        occurred_at_ms: int,
    ) -> tuple[MissionRecord, bool]: ...

    async def list_objectives(self, mission_id: str) -> tuple[ObjectiveRecord, ...]: ...

    async def append_objective(
        self,
        mission_id: str,
        objective: MissionObjective,
        *,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        evidence_refs: tuple[str, ...] = (),
    ) -> ObjectiveRecord: ...

    async def list_missions(
        self, caller_scope: str, *, limit: int = 20, cursor: str | None = None
    ) -> tuple[tuple[MissionRecord, ...], str | None]: ...

    async def transition_mission(
        self,
        mission_id: str,
        *,
        expected_version: int,
        target: MissionStatus,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> MissionRecord: ...

    async def transition_objective(
        self,
        mission_id: str,
        objective_id: str,
        *,
        expected_version: int,
        target: ObjectiveStatus,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ObjectiveRecord: ...

    async def append_transition(self, draft: MissionTransitionDraft) -> MissionTransitionRecord: ...

    async def save_proposal(
        self,
        proposal: GoalProposal,
        decision: GoalAdmissionDecision,
        *,
        occurred_at_ms: int,
    ) -> None: ...

    async def save_budget(
        self, mission_id: str, budget: BudgetAccount, *, updated_at_ms: int
    ) -> None: ...

    async def link_evidence(self, link: MissionEvidenceLink) -> None: ...

    async def save_presentation_artifact(self, artifact: PresentationArtifact) -> None: ...

    async def snapshot(self, mission_id: str) -> MissionSnapshot: ...


class InMemoryMissionRepository:
    """Deterministic repository for domain and coordinator tests."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._missions: dict[str, MissionRecord] = {}
        self._requests: dict[tuple[str, str], tuple[str, str]] = {}
        self._objectives: dict[str, tuple[ObjectiveRecord, ...]] = {}
        self._transitions: dict[str, list[MissionTransitionRecord]] = {}
        self._proposals: dict[str, list[StoredGoalProposal]] = {}
        self._budgets: dict[str, BudgetAccount] = {}
        self._evidence: dict[str, list[MissionEvidenceLink]] = {}
        self._artifacts: dict[str, list[PresentationArtifact]] = {}
        self._transition_id = 0

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def create_mission(
        self,
        *,
        caller_scope: str,
        request_id: str,
        spec: MissionSpec,
        occurred_at_ms: int,
    ) -> tuple[MissionRecord, bool]:
        async with self._lock:
            key = (caller_scope, request_id)
            existing = self._requests.get(key)
            if existing is not None:
                request_hash, mission_id = existing
                if request_hash != spec.canonical_hash:
                    raise MissionIdempotencyConflictError("IDEMPOTENCY_CONFLICT")
                return self._missions[mission_id].model_copy(deep=True), True
            if spec.mission_id in self._missions:
                raise MissionIdempotencyConflictError("IDEMPOTENCY_CONFLICT")
            record = MissionRecord(
                caller_scope=caller_scope,
                request_id=request_id,
                request_hash=spec.canonical_hash,
                spec=spec,
                created_at_ms=occurred_at_ms,
                updated_at_ms=occurred_at_ms,
            )
            self._missions[spec.mission_id] = record
            self._requests[key] = (spec.canonical_hash, spec.mission_id)
            self._objectives[spec.mission_id] = tuple(
                ObjectiveRecord(
                    mission_id=spec.mission_id,
                    ordinal=ordinal,
                    objective=objective,
                )
                for ordinal, objective in enumerate(spec.objectives)
            )
            self._transitions[spec.mission_id] = []
            self._proposals[spec.mission_id] = []
            self._evidence[spec.mission_id] = []
            self._artifacts[spec.mission_id] = []
            return record.model_copy(deep=True), False

    async def list_objectives(self, mission_id: str) -> tuple[ObjectiveRecord, ...]:
        return tuple(item.model_copy(deep=True) for item in self._objectives[mission_id])

    async def append_objective(
        self,
        mission_id: str,
        objective: MissionObjective,
        *,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        evidence_refs: tuple[str, ...] = (),
    ) -> ObjectiveRecord:
        async with self._lock:
            records = self._objectives[mission_id]
            if any(record.objective.objective_id == objective.objective_id for record in records):
                raise MissionIdempotencyConflictError("IDEMPOTENCY_CONFLICT")
            record = ObjectiveRecord(
                mission_id=mission_id,
                ordinal=len(records),
                objective=objective,
            )
            self._objectives[mission_id] = (*records, record)
            self._transition_id += 1
            self._transitions[mission_id].append(
                MissionTransitionRecord(
                    transition_id=self._transition_id,
                    mission_id=mission_id,
                    objective_id=objective.objective_id,
                    entity_version=0,
                    from_state=None,
                    to_state=ObjectiveStatus.PENDING.value,
                    reason_code=reason_code,
                    actor=actor,
                    evidence_refs=evidence_refs,
                    occurred_at_ms=occurred_at_ms,
                )
            )
            return record.model_copy(deep=True)

    async def list_missions(
        self, caller_scope: str, *, limit: int = 20, cursor: str | None = None
    ) -> tuple[tuple[MissionRecord, ...], str | None]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after = _decode_cursor(cursor)
        ordered = sorted(
            (
                record
                for record in self._missions.values()
                if record.caller_scope == caller_scope
                and (record.created_at_ms, record.spec.mission_id) > after
            ),
            key=lambda record: (record.created_at_ms, record.spec.mission_id),
        )
        selected = ordered[: limit + 1]
        page = selected[:limit]
        next_cursor = _encode_cursor(page[-1]) if len(selected) > limit else None
        return tuple(item.model_copy(deep=True) for item in page), next_cursor

    async def transition_mission(
        self,
        mission_id: str,
        *,
        expected_version: int,
        target: MissionStatus,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> MissionRecord:
        from .state_machine import validate_mission_transition

        async with self._lock:
            current = self._missions[mission_id]
            if current.version != expected_version:
                raise ValueError("STALE_MISSION_VERSION")
            validate_mission_transition(current.status, target)
            updated = current.model_copy(
                update={
                    "status": target,
                    "version": current.version + 1,
                    "updated_at_ms": occurred_at_ms,
                }
            )
            self._missions[mission_id] = updated
            self._transition_id += 1
            self._transitions[mission_id].append(
                MissionTransitionRecord(
                    transition_id=self._transition_id,
                    mission_id=mission_id,
                    entity_version=updated.version,
                    from_state=current.status.value,
                    to_state=target.value,
                    reason_code=reason_code,
                    actor=actor,
                    details=details or {},
                    evidence_refs=evidence_refs,
                    occurred_at_ms=occurred_at_ms,
                )
            )
            return updated.model_copy(deep=True)

    async def transition_objective(
        self,
        mission_id: str,
        objective_id: str,
        *,
        expected_version: int,
        target: ObjectiveStatus,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ObjectiveRecord:
        from .state_machine import validate_objective_transition

        async with self._lock:
            records = list(self._objectives[mission_id])
            index = next(
                index
                for index, record in enumerate(records)
                if record.objective.objective_id == objective_id
            )
            current = records[index]
            if current.version != expected_version:
                raise ValueError("STALE_OBJECTIVE_VERSION")
            validate_objective_transition(current.status, target)
            updated = current.model_copy(update={"status": target, "version": current.version + 1})
            records[index] = updated
            self._objectives[mission_id] = tuple(records)
            self._transition_id += 1
            self._transitions[mission_id].append(
                MissionTransitionRecord(
                    transition_id=self._transition_id,
                    mission_id=mission_id,
                    objective_id=objective_id,
                    entity_version=updated.version,
                    from_state=current.status.value,
                    to_state=target.value,
                    reason_code=reason_code,
                    actor=actor,
                    details=details or {},
                    evidence_refs=evidence_refs,
                    occurred_at_ms=occurred_at_ms,
                )
            )
            return updated.model_copy(deep=True)

    async def append_transition(self, draft: MissionTransitionDraft) -> MissionTransitionRecord:
        async with self._lock:
            if draft.mission_id not in self._missions:
                raise KeyError(draft.mission_id)
            self._transition_id += 1
            record = MissionTransitionRecord(
                transition_id=self._transition_id,
                **draft.model_dump(mode="python"),
            )
            self._transitions[draft.mission_id].append(record)
            return record.model_copy(deep=True)

    async def save_proposal(
        self,
        proposal: GoalProposal,
        decision: GoalAdmissionDecision,
        *,
        occurred_at_ms: int,
    ) -> None:
        records = self._proposals[proposal.mission_id]
        stored = StoredGoalProposal(
            proposal=proposal,
            decision=decision,
            occurred_at_ms=occurred_at_ms,
        )
        existing = next(
            (item for item in records if item.proposal.proposal_id == proposal.proposal_id),
            None,
        )
        if existing is not None and existing != stored:
            raise MissionIdempotencyConflictError("IDEMPOTENCY_CONFLICT")
        if existing is None:
            records.append(stored)

    async def save_budget(
        self, mission_id: str, budget: BudgetAccount, *, updated_at_ms: int
    ) -> None:
        del updated_at_ms
        if mission_id not in self._missions:
            raise KeyError(mission_id)
        self._budgets[mission_id] = budget.model_copy(deep=True)

    async def link_evidence(self, link: MissionEvidenceLink) -> None:
        links = self._evidence[link.mission_id]
        if all(existing.link_id != link.link_id for existing in links):
            links.append(link)

    async def save_presentation_artifact(self, artifact: PresentationArtifact) -> None:
        artifacts = self._artifacts[artifact.mission_id]
        if all(existing.artifact_id != artifact.artifact_id for existing in artifacts):
            artifacts.append(artifact)

    async def snapshot(self, mission_id: str) -> MissionSnapshot:
        return MissionSnapshot(
            mission=self._missions[mission_id].model_copy(deep=True),
            objectives=await self.list_objectives(mission_id),
            transitions=tuple(item.model_copy(deep=True) for item in self._transitions[mission_id]),
            proposals=tuple(item.model_copy(deep=True) for item in self._proposals[mission_id]),
            budget=self._budgets.get(mission_id),
            evidence_links=tuple(item.model_copy(deep=True) for item in self._evidence[mission_id]),
            presentation_artifacts=tuple(
                item.model_copy(deep=True) for item in self._artifacts[mission_id]
            ),
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
  mission_id TEXT PRIMARY KEY,
  caller_scope TEXT NOT NULL,
  request_id TEXT NOT NULL,
  request_hash TEXT NOT NULL CHECK(length(request_hash) = 64),
  spec_json TEXT NOT NULL,
  status TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  UNIQUE(caller_scope, request_id)
);
CREATE TABLE IF NOT EXISTS mission_objectives (
  mission_id TEXT NOT NULL REFERENCES missions(mission_id),
  objective_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  objective_json TEXT NOT NULL,
  status TEXT NOT NULL,
  version INTEGER NOT NULL,
  PRIMARY KEY(mission_id, objective_id),
  UNIQUE(mission_id, ordinal)
);
CREATE TABLE IF NOT EXISTS mission_transitions (
  transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_id TEXT NOT NULL REFERENCES missions(mission_id),
  objective_id TEXT,
  entity_version INTEGER NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  actor TEXT NOT NULL,
  details_json TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  occurred_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS goal_proposals (
  proposal_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL REFERENCES missions(mission_id),
  proposal_json TEXT NOT NULL,
  decision_json TEXT NOT NULL,
  occurred_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mission_budgets (
  mission_id TEXT PRIMARY KEY REFERENCES missions(mission_id),
  account_json TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mission_evidence_links (
  link_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL REFERENCES missions(mission_id),
  objective_id TEXT,
  evidence_kind TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  command_id TEXT,
  attributable INTEGER NOT NULL,
  linked_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS presentation_artifacts (
  artifact_id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL REFERENCES missions(mission_id),
  stage_id TEXT NOT NULL,
  artifact_kind TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  captured_at_ms INTEGER NOT NULL,
  sanitized INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mission_objectives_status
ON mission_objectives(mission_id, status, ordinal);
CREATE INDEX IF NOT EXISTS idx_mission_transitions_entity
ON mission_transitions(mission_id, objective_id, transition_id);
CREATE INDEX IF NOT EXISTS idx_mission_evidence
ON mission_evidence_links(mission_id, objective_id, linked_at_ms);
"""


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _decode_cursor(cursor: str | None) -> tuple[int, str]:
    if cursor is None:
        return (-1, "")
    timestamp, separator, mission_id = cursor.partition(":")
    if not separator or not timestamp.isdigit() or not mission_id:
        raise ValueError("invalid mission cursor")
    return int(timestamp), mission_id


def _encode_cursor(record: MissionRecord) -> str:
    return f"{record.created_at_ms}:{record.spec.mission_id}"


def _load_budget_account(payload: str) -> BudgetAccount:
    value = json.loads(payload)
    protected = value.get("limit", {}).get("protected_items")
    if isinstance(protected, list):
        value["limit"]["protected_items"] = frozenset(protected)
    return BudgetAccount.model_validate(value)


class SQLiteMissionRepository:
    """Additive mission tables stored beside the authoritative command journal."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._db: Any = None
        self._lock = asyncio.Lock()

    def _require_db(self) -> Any:
        if self._db is None:
            raise RuntimeError("mission repository is not connected")
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
    def _row_to_mission(row: Any) -> MissionRecord:
        return MissionRecord(
            caller_scope=row["caller_scope"],
            request_id=row["request_id"],
            request_hash=row["request_hash"],
            spec=MissionSpec.model_validate(json.loads(row["spec_json"])),
            status=MissionStatus(row["status"]),
            version=row["version"],
            created_at_ms=row["created_at_ms"],
            updated_at_ms=row["updated_at_ms"],
        )

    async def _find_by_request(self, caller_scope: str, request_id: str) -> Any:
        cursor = await self._require_db().execute(
            "SELECT * FROM missions WHERE caller_scope=? AND request_id=?",
            (caller_scope, request_id),
        )
        return await cursor.fetchone()

    async def create_mission(
        self,
        *,
        caller_scope: str,
        request_id: str,
        spec: MissionSpec,
        occurred_at_ms: int,
    ) -> tuple[MissionRecord, bool]:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing = await self._find_by_request(caller_scope, request_id)
                if existing is not None:
                    if existing["request_hash"] != spec.canonical_hash:
                        raise MissionIdempotencyConflictError("IDEMPOTENCY_CONFLICT")
                    await db.commit()
                    return self._row_to_mission(existing), True
                await db.execute(
                    """INSERT INTO missions
                    (mission_id,caller_scope,request_id,request_hash,spec_json,status,
                     version,created_at_ms,updated_at_ms)
                    VALUES (?,?,?,?,?,'accepted',0,?,?)""",
                    (
                        spec.mission_id,
                        caller_scope,
                        request_id,
                        spec.canonical_hash,
                        _dump(spec.canonical_payload()),
                        occurred_at_ms,
                        occurred_at_ms,
                    ),
                )
                for ordinal, objective in enumerate(spec.objectives):
                    await db.execute(
                        """INSERT INTO mission_objectives
                        (mission_id,objective_id,ordinal,objective_json,status,version)
                        VALUES (?,?,?,?,'pending',0)""",
                        (
                            spec.mission_id,
                            objective.objective_id,
                            ordinal,
                            _dump(objective.canonical_payload()),
                        ),
                    )
                await db.commit()
                return (
                    MissionRecord(
                        caller_scope=caller_scope,
                        request_id=request_id,
                        request_hash=spec.canonical_hash,
                        spec=spec,
                        created_at_ms=occurred_at_ms,
                        updated_at_ms=occurred_at_ms,
                    ),
                    False,
                )
            except Exception:
                await db.rollback()
                raise

    async def _mission(self, mission_id: str) -> MissionRecord:
        cursor = await self._require_db().execute(
            "SELECT * FROM missions WHERE mission_id=?", (mission_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(mission_id)
        return self._row_to_mission(row)

    async def list_objectives(self, mission_id: str) -> tuple[ObjectiveRecord, ...]:
        cursor = await self._require_db().execute(
            "SELECT * FROM mission_objectives WHERE mission_id=? ORDER BY ordinal",
            (mission_id,),
        )
        return tuple(
            ObjectiveRecord(
                mission_id=row["mission_id"],
                ordinal=row["ordinal"],
                objective=MissionObjective.model_validate(json.loads(row["objective_json"])),
                status=ObjectiveStatus(row["status"]),
                version=row["version"],
            )
            for row in await cursor.fetchall()
        )

    async def append_objective(
        self,
        mission_id: str,
        objective: MissionObjective,
        *,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        evidence_refs: tuple[str, ...] = (),
    ) -> ObjectiveRecord:
        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM mission_objectives WHERE mission_id=?",
                    (mission_id,),
                )
                row = await cursor.fetchone()
                ordinal = int(row[0])
                await db.execute(
                    """INSERT INTO mission_objectives
                    (mission_id,objective_id,ordinal,objective_json,status,version)
                    VALUES (?,?,?,?,'pending',0)""",
                    (
                        mission_id,
                        objective.objective_id,
                        ordinal,
                        _dump(objective.canonical_payload()),
                    ),
                )
                await db.execute(
                    """INSERT INTO mission_transitions
                    (mission_id,objective_id,entity_version,from_state,to_state,
                     reason_code,actor,details_json,evidence_refs_json,occurred_at_ms)
                    VALUES (?,?,0,NULL,'pending',?,?,?,?,?)""",
                    (
                        mission_id,
                        objective.objective_id,
                        reason_code,
                        actor,
                        _dump({}),
                        _dump(evidence_refs),
                        occurred_at_ms,
                    ),
                )
                await db.commit()
                return ObjectiveRecord(
                    mission_id=mission_id,
                    ordinal=ordinal,
                    objective=objective,
                )
            except Exception as exc:
                await db.rollback()
                if "UNIQUE constraint failed" in str(exc):
                    raise MissionIdempotencyConflictError("IDEMPOTENCY_CONFLICT") from exc
                raise

    async def list_missions(
        self, caller_scope: str, *, limit: int = 20, cursor: str | None = None
    ) -> tuple[tuple[MissionRecord, ...], str | None]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        after_ms, after_id = _decode_cursor(cursor)
        rows_cursor = await self._require_db().execute(
            """SELECT * FROM missions WHERE caller_scope=?
            AND (created_at_ms>? OR (created_at_ms=? AND mission_id>?))
            ORDER BY created_at_ms,mission_id LIMIT ?""",
            (caller_scope, after_ms, after_ms, after_id, limit + 1),
        )
        selected = await rows_cursor.fetchall()
        page_rows = selected[:limit]
        page = tuple(self._row_to_mission(row) for row in page_rows)
        next_cursor = _encode_cursor(page[-1]) if len(selected) > limit else None
        return page, next_cursor

    async def transition_mission(
        self,
        mission_id: str,
        *,
        expected_version: int,
        target: MissionStatus,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> MissionRecord:
        from .state_machine import validate_mission_transition

        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                current = await self._mission(mission_id)
                if current.version != expected_version:
                    raise ValueError("STALE_MISSION_VERSION")
                validate_mission_transition(current.status, target)
                changed = await db.execute(
                    """UPDATE missions SET status=?,version=version+1,updated_at_ms=?
                    WHERE mission_id=? AND version=?""",
                    (target.value, occurred_at_ms, mission_id, expected_version),
                )
                if changed.rowcount != 1:
                    raise ValueError("STALE_MISSION_VERSION")
                await db.execute(
                    """INSERT INTO mission_transitions
                    (mission_id,objective_id,entity_version,from_state,to_state,
                     reason_code,actor,details_json,evidence_refs_json,occurred_at_ms)
                    VALUES (?,NULL,?,?,?,?,?,?,?,?)""",
                    (
                        mission_id,
                        expected_version + 1,
                        current.status.value,
                        target.value,
                        reason_code,
                        actor,
                        _dump(details or {}),
                        _dump(evidence_refs),
                        occurred_at_ms,
                    ),
                )
                await db.commit()
                return current.model_copy(
                    update={
                        "status": target,
                        "version": expected_version + 1,
                        "updated_at_ms": occurred_at_ms,
                    }
                )
            except Exception:
                await db.rollback()
                raise

    async def transition_objective(
        self,
        mission_id: str,
        objective_id: str,
        *,
        expected_version: int,
        target: ObjectiveStatus,
        reason_code: str,
        actor: str,
        occurred_at_ms: int,
        details: dict[str, Any] | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> ObjectiveRecord:
        from .state_machine import validate_objective_transition

        db = self._require_db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """SELECT * FROM mission_objectives
                    WHERE mission_id=? AND objective_id=?""",
                    (mission_id, objective_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise KeyError(objective_id)
                current = ObjectiveRecord(
                    mission_id=row["mission_id"],
                    ordinal=row["ordinal"],
                    objective=MissionObjective.model_validate(json.loads(row["objective_json"])),
                    status=ObjectiveStatus(row["status"]),
                    version=row["version"],
                )
                if current.version != expected_version:
                    raise ValueError("STALE_OBJECTIVE_VERSION")
                validate_objective_transition(current.status, target)
                changed = await db.execute(
                    """UPDATE mission_objectives SET status=?,version=version+1
                    WHERE mission_id=? AND objective_id=? AND version=?""",
                    (target.value, mission_id, objective_id, expected_version),
                )
                if changed.rowcount != 1:
                    raise ValueError("STALE_OBJECTIVE_VERSION")
                await db.execute(
                    """INSERT INTO mission_transitions
                    (mission_id,objective_id,entity_version,from_state,to_state,
                     reason_code,actor,details_json,evidence_refs_json,occurred_at_ms)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        mission_id,
                        objective_id,
                        expected_version + 1,
                        current.status.value,
                        target.value,
                        reason_code,
                        actor,
                        _dump(details or {}),
                        _dump(evidence_refs),
                        occurred_at_ms,
                    ),
                )
                await db.commit()
                return current.model_copy(
                    update={"status": target, "version": expected_version + 1}
                )
            except Exception:
                await db.rollback()
                raise

    async def append_transition(self, draft: MissionTransitionDraft) -> MissionTransitionRecord:
        cursor = await self._require_db().execute(
            """INSERT INTO mission_transitions
            (mission_id,objective_id,entity_version,from_state,to_state,reason_code,
             actor,details_json,evidence_refs_json,occurred_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                draft.mission_id,
                draft.objective_id,
                draft.entity_version,
                draft.from_state,
                draft.to_state,
                draft.reason_code,
                draft.actor,
                _dump(draft.details),
                _dump(draft.evidence_refs),
                draft.occurred_at_ms,
            ),
        )
        await self._require_db().commit()
        return MissionTransitionRecord(
            transition_id=int(cursor.lastrowid),
            **draft.model_dump(mode="python"),
        )

    async def save_proposal(
        self,
        proposal: GoalProposal,
        decision: GoalAdmissionDecision,
        *,
        occurred_at_ms: int,
    ) -> None:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT proposal_json,decision_json,occurred_at_ms FROM goal_proposals WHERE proposal_id=?",
            (proposal.proposal_id,),
        )
        existing = await cursor.fetchone()
        values = (
            _dump(proposal.canonical_payload()),
            _dump(decision.canonical_payload()),
            occurred_at_ms,
        )
        if existing is not None:
            if tuple(existing) != values:
                raise MissionIdempotencyConflictError("IDEMPOTENCY_CONFLICT")
            return
        await db.execute(
            "INSERT INTO goal_proposals VALUES (?,?,?,?,?)",
            (proposal.proposal_id, proposal.mission_id, *values),
        )
        await db.commit()

    async def save_budget(
        self, mission_id: str, budget: BudgetAccount, *, updated_at_ms: int
    ) -> None:
        await self._require_db().execute(
            """INSERT INTO mission_budgets VALUES (?,?,?)
            ON CONFLICT(mission_id) DO UPDATE SET
            account_json=excluded.account_json,updated_at_ms=excluded.updated_at_ms""",
            (mission_id, _dump(budget.model_dump(mode="json")), updated_at_ms),
        )
        await self._require_db().commit()

    async def link_evidence(self, link: MissionEvidenceLink) -> None:
        await self._require_db().execute(
            "INSERT OR IGNORE INTO mission_evidence_links VALUES (?,?,?,?,?,?,?,?)",
            (
                link.link_id,
                link.mission_id,
                link.objective_id,
                link.evidence_kind,
                link.evidence_ref,
                link.command_id,
                int(link.attributable),
                link.linked_at_ms,
            ),
        )
        await self._require_db().commit()

    async def save_presentation_artifact(self, artifact: PresentationArtifact) -> None:
        await self._require_db().execute(
            "INSERT OR IGNORE INTO presentation_artifacts VALUES (?,?,?,?,?,?,?,?)",
            (
                artifact.artifact_id,
                artifact.mission_id,
                artifact.stage_id,
                artifact.artifact_kind,
                artifact.path,
                artifact.sha256,
                artifact.captured_at_ms,
                int(artifact.sanitized),
            ),
        )
        await self._require_db().commit()

    async def snapshot(self, mission_id: str) -> MissionSnapshot:
        db = self._require_db()
        mission = await self._mission(mission_id)
        transition_cursor = await db.execute(
            "SELECT * FROM mission_transitions WHERE mission_id=? ORDER BY transition_id",
            (mission_id,),
        )
        transitions = tuple(
            MissionTransitionRecord(
                transition_id=row["transition_id"],
                mission_id=row["mission_id"],
                objective_id=row["objective_id"],
                entity_version=row["entity_version"],
                from_state=row["from_state"],
                to_state=row["to_state"],
                reason_code=row["reason_code"],
                actor=row["actor"],
                details=json.loads(row["details_json"]),
                evidence_refs=tuple(json.loads(row["evidence_refs_json"])),
                occurred_at_ms=row["occurred_at_ms"],
            )
            for row in await transition_cursor.fetchall()
        )
        proposal_cursor = await db.execute(
            "SELECT * FROM goal_proposals WHERE mission_id=? ORDER BY occurred_at_ms,proposal_id",
            (mission_id,),
        )
        proposals = tuple(
            StoredGoalProposal(
                proposal=GoalProposal.model_validate(json.loads(row["proposal_json"])),
                decision=GoalAdmissionDecision.model_validate(json.loads(row["decision_json"])),
                occurred_at_ms=row["occurred_at_ms"],
            )
            for row in await proposal_cursor.fetchall()
        )
        budget_cursor = await db.execute(
            "SELECT account_json FROM mission_budgets WHERE mission_id=?", (mission_id,)
        )
        budget_row = await budget_cursor.fetchone()
        evidence_cursor = await db.execute(
            "SELECT * FROM mission_evidence_links WHERE mission_id=? ORDER BY linked_at_ms,link_id",
            (mission_id,),
        )
        evidence = tuple(
            MissionEvidenceLink(
                link_id=row["link_id"],
                mission_id=row["mission_id"],
                objective_id=row["objective_id"],
                evidence_kind=row["evidence_kind"],
                evidence_ref=row["evidence_ref"],
                command_id=row["command_id"],
                attributable=bool(row["attributable"]),
                linked_at_ms=row["linked_at_ms"],
            )
            for row in await evidence_cursor.fetchall()
        )
        artifact_cursor = await db.execute(
            "SELECT * FROM presentation_artifacts WHERE mission_id=? ORDER BY captured_at_ms,artifact_id",
            (mission_id,),
        )
        artifacts = tuple(
            PresentationArtifact(
                artifact_id=row["artifact_id"],
                mission_id=row["mission_id"],
                stage_id=row["stage_id"],
                artifact_kind=row["artifact_kind"],
                path=row["path"],
                sha256=row["sha256"],
                captured_at_ms=row["captured_at_ms"],
                sanitized=bool(row["sanitized"]),
            )
            for row in await artifact_cursor.fetchall()
        )
        return MissionSnapshot(
            mission=mission,
            objectives=await self.list_objectives(mission_id),
            transitions=transitions,
            proposals=proposals,
            budget=_load_budget_account(budget_row[0]) if budget_row else None,
            evidence_links=evidence,
            presentation_artifacts=artifacts,
        )
