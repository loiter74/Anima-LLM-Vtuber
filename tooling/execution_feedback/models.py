from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SAFE_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def validate_identifier(value: str) -> str:
    if _SAFE_ID.fullmatch(value) is None:
        raise ValueError("identifier must use safe kebab-case")
    return value


def validate_sha256(value: str, *, field_name: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


class FeedbackStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMED_OUT = "timed_out"
    IN_PROGRESS = "in_progress"
    CANCELLED = "cancelled"


class PlanAggregateStatus(StrEnum):
    PASSED = "passed"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    BLOCKED = "blocked"


class FeedbackEventKind(StrEnum):
    STARTED = "started"
    PROGRESS = "progress"


class ResourceKind(StrEnum):
    PROCESS = "process"
    CONTAINER = "container"


class ResourceOwnership(StrEnum):
    OWNED = "owned"
    PROTECTED_EXTERNAL = "protected_external"


class CleanupStrategy(StrEnum):
    NONE = "none"
    TERMINATE_PROCESS_GROUP = "terminate_process_group"
    STOP_CONTAINER = "stop_container"


class LeaseState(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ORPHANED_WITHOUT_AUTHORITY = "orphaned_without_authority"


class LeaseDecision(StrEnum):
    MATCHING = "matching"
    EXPIRED = "expired"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    IDENTITY_MISMATCH = "identity_mismatch"
    PROTECTED_EXTERNAL = "protected_external"
    TAKEN_OVER = "taken_over"
    TERMINATION_FAILED = "termination_failed"


class FeedbackBudget(FrozenModel):
    action_seconds: float = Field(default=240, gt=0, le=300)
    evidence_seconds: float = Field(default=30, gt=0, le=300)
    cleanup_seconds: float = Field(default=30, gt=0, le=300)
    heartbeat_seconds: float = Field(default=60, gt=0, le=300)

    @property
    def deadline_seconds(self) -> float:
        return self.action_seconds + self.evidence_seconds + self.cleanup_seconds

    @model_validator(mode="after")
    def validate_deadline(self) -> FeedbackBudget:
        if self.deadline_seconds > 300:
            raise ValueError("feedback budget must not exceed 300 seconds")
        if self.heartbeat_seconds > self.action_seconds:
            raise ValueError("heartbeat interval must not exceed the action budget")
        return self


class PlanStepSpec(FrozenModel):
    id: str
    action_kind: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    required: bool = True
    resumable: bool = True
    budget: FeedbackBudget = FeedbackBudget()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("depends_on", mode="before")
    @classmethod
    def validate_dependencies(cls, value: object) -> object:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("depends_on must be a list or tuple")
        return tuple(validate_identifier(str(item)) for item in value)


class ExecutionPlanManifest(FrozenModel):
    schema_version: Literal[1] = 1
    run_id: str
    input_fingerprint: str
    steps: tuple[PlanStepSpec, ...] = Field(min_length=1)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("input_fingerprint")
    @classmethod
    def validate_input_fingerprint(cls, value: str) -> str:
        return validate_sha256(value, field_name="input_fingerprint")

    @model_validator(mode="after")
    def validate_graph(self) -> ExecutionPlanManifest:
        step_ids = tuple(step.id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("step IDs must be unique")
        known = set(step_ids)
        for step in self.steps:
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(f"step {step.id!r} references unknown step {sorted(unknown)!r}")

        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {step.id: step for step in self.steps}

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError(f"execution plan contains a dependency cycle at {step_id!r}")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in by_id[step_id].depends_on:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return self


class PlanStepCheckpoint(FrozenModel):
    schema_version: Literal[1] = 1
    run_id: str
    step_id: str
    status: FeedbackStatus
    reuse_fingerprint: str
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    result_reference: str = Field(min_length=1)
    committed_at: datetime

    @field_validator("run_id", "step_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("reuse_fingerprint")
    @classmethod
    def validate_reuse_fingerprint(cls, value: str) -> str:
        return validate_sha256(value, field_name="reuse_fingerprint")

    @field_validator("committed_at")
    @classmethod
    def validate_committed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("committed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_success(self) -> PlanStepCheckpoint:
        if self.status is not FeedbackStatus.PASSED:
            raise ValueError("only passed steps can be committed as reusable checkpoints")
        return self


class PlanRecovery(FrozenModel):
    reusable_steps: tuple[str, ...] = ()
    invalidated_steps: dict[str, str] = Field(default_factory=dict)
    continuation_results: tuple[FeedbackWindowResult, ...] = ()


class PlanAggregate(FrozenModel):
    status: PlanAggregateStatus
    nonpassing_required_steps: tuple[str, ...] = ()


class ContinuationRequest(FrozenModel):
    schema_version: Literal[1] = 1
    request_id: str
    run_id: str
    step_id: str
    requested_at: datetime

    @field_validator("request_id", "run_id", "step_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("requested_at")
    @classmethod
    def validate_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        return value


class CheckpointRef(FrozenModel):
    kind: str = Field(min_length=1)
    reference: str = Field(min_length=1)


class ResourceLeaseRef(FrozenModel):
    lease_id: str
    reference: str = Field(min_length=1)

    @field_validator("lease_id")
    @classmethod
    def validate_lease_id(cls, value: str) -> str:
        return validate_identifier(value)


class ResourceIdentity(FrozenModel):
    kind: ResourceKind
    resource_id: str = Field(min_length=1)
    creation_token: str = Field(min_length=1)
    project: str | None = None


class ResourceObservation(FrozenModel):
    identity: ResourceIdentity
    running: bool
    exit_code: int | None = None

    @model_validator(mode="after")
    def validate_exit_code(self) -> ResourceObservation:
        if self.running and self.exit_code is not None:
            raise ValueError("running resources must not have an exit code")
        return self


class ResourceLease(FrozenModel):
    schema_version: Literal[1] = 1
    lease_id: str
    run_id: str
    owner: str
    identity: ResourceIdentity
    command_digest: str
    log_path: str = Field(min_length=1)
    created_at: datetime
    heartbeat_at: datetime
    ttl_seconds: float = Field(gt=0, le=86_400)
    cleanup_strategy: CleanupStrategy
    ownership: ResourceOwnership = ResourceOwnership.OWNED
    state: LeaseState = LeaseState.ACTIVE

    @field_validator("lease_id", "run_id", "owner")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("command_digest")
    @classmethod
    def validate_command_digest(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("command_digest must be a lowercase SHA-256 digest")
        return value

    @field_validator("created_at", "heartbeat_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("lease timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_ownership(self) -> ResourceLease:
        if self.heartbeat_at < self.created_at:
            raise ValueError("heartbeat_at must not precede created_at")
        if (
            self.ownership is ResourceOwnership.PROTECTED_EXTERNAL
            and self.cleanup_strategy is not CleanupStrategy.NONE
        ):
            raise ValueError("protected external resources require cleanup strategy none")
        if (
            self.ownership is ResourceOwnership.OWNED
            and self.cleanup_strategy is CleanupStrategy.NONE
        ):
            raise ValueError("owned resources require an exact cleanup strategy")
        return self

    def to_ref(self) -> ResourceLeaseRef:
        return ResourceLeaseRef(
            lease_id=self.lease_id,
            reference=f"lease:{self.run_id}:{self.lease_id}",
        )


class LeaseInspection(FrozenModel):
    decision: LeaseDecision
    lease: ResourceLease
    observation: ResourceObservation
    authority_to_terminate: bool
    reason: str = Field(min_length=1)


class ArtifactRecovery(FrozenModel):
    result: FeedbackWindowResult | None = None
    latest_window_sequence: int | None = Field(default=None, ge=1)
    rejected_artifacts: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_result_sequence(self) -> ArtifactRecovery:
        if self.result is None and self.latest_window_sequence is not None:
            raise ValueError("latest window sequence requires a valid result")
        if self.result is not None and self.latest_window_sequence != self.result.window_sequence:
            raise ValueError("latest window sequence must match the recovered result")
        return self


class FailureReflection(FrozenModel):
    fingerprint: str = Field(min_length=1)
    occurrence_count: int = Field(ge=1)
    evidence_refs: tuple[str, ...] = ()
    excluded_causes: tuple[str, ...] = ()
    root_cause_hypotheses: tuple[str, ...] = ()
    missing_diagnostics: tuple[str, ...] = ()
    affected_resources: tuple[str, ...] = ()
    next_action: str = Field(min_length=1)
    circuit_open: bool = False


class FailureRecord(FrozenModel):
    schema_version: Literal[1] = 1
    fingerprint: str
    run_id: str
    step_id: str
    step_kind: str = Field(min_length=1)
    error_code: str = Field(min_length=1)
    failure_layer: str = Field(min_length=1)
    occurred_at: datetime
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    location: str = Field(min_length=1)
    excluded_causes: tuple[str, ...] = ()
    root_cause_hypotheses: tuple[str, ...] = ()
    missing_diagnostics: tuple[str, ...] = ()
    affected_resources: tuple[str, ...] = ()

    @field_validator("fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str) -> str:
        return validate_sha256(value, field_name="fingerprint")

    @field_validator("run_id", "step_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class FailureCircuitState(FrozenModel):
    schema_version: Literal[1] = 1
    fingerprint: str
    occurrences: tuple[FailureRecord, ...] = ()
    circuit_open: bool = False
    reflection: FailureReflection | None = None
    superseded_by: str | None = None
    reset_reason: str | None = None
    reset_at: datetime | None = None

    @field_validator("fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str) -> str:
        return validate_sha256(value, field_name="fingerprint")

    @field_validator("superseded_by")
    @classmethod
    def validate_superseded_by(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_sha256(value, field_name="superseded_by")

    @field_validator("reset_at")
    @classmethod
    def validate_reset_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("reset_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> FailureCircuitState:
        if any(record.fingerprint != self.fingerprint for record in self.occurrences):
            raise ValueError("failure occurrence fingerprint must match circuit fingerprint")
        if self.circuit_open and self.reflection is None:
            raise ValueError("an open failure circuit requires a reflection")
        if self.reflection is not None and self.reflection.fingerprint != self.fingerprint:
            raise ValueError("reflection fingerprint must match circuit fingerprint")
        reset_fields = (self.superseded_by, self.reset_reason, self.reset_at)
        if any(field is not None for field in reset_fields) and not all(
            field is not None for field in reset_fields
        ):
            raise ValueError("failure circuit reset fields must be recorded together")
        return self


class FailureAuthorization(FrozenModel):
    allowed: bool
    reason: str = Field(min_length=1)
    reflection: FailureReflection | None = None


class ActionResult(FrozenModel):
    status: FeedbackStatus
    progress_summary: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    checkpoint: CheckpointRef | None = None
    lease: ResourceLeaseRef | None = None
    failure_fingerprint: str | None = None
    next_action: str = Field(default="advance", min_length=1)

    @model_validator(mode="after")
    def validate_continuation(self) -> ActionResult:
        if self.status is FeedbackStatus.IN_PROGRESS and not (self.checkpoint or self.lease):
            raise ValueError("in_progress action requires a checkpoint or resource lease")
        return self

    @classmethod
    def passed(cls, *, progress_summary: str, next_action: str = "advance") -> ActionResult:
        return cls(
            status=FeedbackStatus.PASSED,
            progress_summary=progress_summary,
            next_action=next_action,
        )


class FeedbackEvent(FrozenModel):
    schema_version: Literal[1] = 1
    run_id: str
    step_id: str
    window_sequence: int = Field(ge=1)
    kind: FeedbackEventKind
    emitted_at: datetime
    elapsed_seconds: float = Field(ge=0)
    phase: str = Field(min_length=1)
    evidence_ref: str | None = None

    @field_validator("run_id", "step_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("emitted_at")
    @classmethod
    def validate_emitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("emitted_at must be timezone-aware")
        return value


class FeedbackWindowResult(FrozenModel):
    schema_version: Literal[1] = 1
    run_id: str
    step_id: str
    window_sequence: int = Field(ge=1)
    status: FeedbackStatus
    started_at: datetime
    feedback_at: datetime
    elapsed_seconds: float = Field(ge=0)
    progress_summary: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    checkpoint: CheckpointRef | None = None
    lease: ResourceLeaseRef | None = None
    failure_fingerprint: str | None = None
    next_action: str = Field(min_length=1)
    cleanup_pending: bool = False

    @field_validator("run_id", "step_id")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return validate_identifier(value)

    @field_validator("started_at", "feedback_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("feedback timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_continuation(self) -> FeedbackWindowResult:
        if self.status is FeedbackStatus.IN_PROGRESS and not (self.checkpoint or self.lease):
            raise ValueError("in_progress result requires a checkpoint or resource lease")
        if self.feedback_at < self.started_at:
            raise ValueError("feedback_at must not precede started_at")
        return self
