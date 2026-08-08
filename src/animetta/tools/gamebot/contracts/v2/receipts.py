"""Receipts, correlation inspection, cancellation, and health contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ._base import V2ContractModel
from .budget import BudgetVector
from .errors import RuntimeProtocolError
from .observations import Position


class ReceiptOutcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class PostObservationStatus(StrEnum):
    STABLE = "stable"
    UNSTABLE = "unstable"
    UNAVAILABLE = "unavailable"


class ReconciliationStatus(StrEnum):
    ACCEPTED = "accepted"
    PENDING = "pending"
    QUARANTINED = "quarantined"


class GoalVerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SettlementRejectionReason(StrEnum):
    SETTLEMENT_DISABLED = "settlement_disabled"
    INITIAL_SAMPLE = "initial_sample"
    MOTION_UNSETTLED = "motion_unsettled"
    DURABLE_STATE_CHANGED = "durable_state_changed"
    STABLE_STREAK_INCOMPLETE = "stable_streak_incomplete"


class SettlementSample(V2ContractModel):
    sample_index: int = Field(ge=0)
    captured_at_ms: int = Field(ge=0)
    position: Position | None = None
    on_ground: bool | None = None
    velocity: Position | None = None
    durable_state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stable_streak: int = Field(ge=0)
    rejection_reason: SettlementRejectionReason | None = None


class ExplainedMutation(V2ContractModel):
    kind: Literal[
        "inventory",
        "block",
        "position",
        "entity",
        "health",
        "combat",
        "advancement",
        "region",
        "other",
    ]
    subject: str = Field(min_length=1, max_length=256)
    delta: float | None = None
    details: dict[str, object] = Field(default_factory=dict)


class CombatTerminalEvidence(V2ContractModel):
    target_entity_id: str = Field(min_length=1, max_length=256)
    target_entity_type: str = Field(min_length=1, max_length=256)
    outcome: Literal["defeated", "escaped", "interrupted"]
    bot_health_before: float = Field(ge=0, le=20)
    bot_health_after: float = Field(ge=0, le=20)
    target_health_before: float = Field(ge=0)
    target_health_after: float | None = Field(default=None, ge=0)
    started_tick: int = Field(ge=0)
    finished_tick: int = Field(ge=0)

    @model_validator(mode="after")
    def _consistent_terminal_outcome(self) -> CombatTerminalEvidence:
        if self.finished_tick < self.started_tick:
            raise ValueError("combat finish tick precedes start tick")
        if self.outcome == "defeated" and self.target_health_after != 0:
            raise ValueError("defeated combat target must have zero terminal health")
        return self


class ActionReceipt(V2ContractModel):
    schema_version: Literal["2"] = "2"
    receipt_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    step_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    parameter_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_sequence: int = Field(gt=0)
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)
    started_tick: int = Field(ge=0)
    finished_tick: int = Field(ge=0)
    outcome: ReceiptOutcome
    error: RuntimeProtocolError | None = None
    post_observation: PostObservationStatus
    reconciliation: ReconciliationStatus
    goal_verification: GoalVerificationStatus
    reconciliation_error: RuntimeProtocolError | None
    settlement_trace: tuple[SettlementSample, ...]
    before_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    explained_mutations: tuple[ExplainedMutation, ...] = ()
    combat: CombatTerminalEvidence | None = None
    budget_usage: BudgetVector
    previous_receipt_hash: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _consistent_outcome(self) -> ActionReceipt:
        if self.finished_at_ms < self.started_at_ms or self.finished_tick < self.started_tick:
            raise ValueError("receipt finish marker must not precede its start marker")
        if self.outcome is ReceiptOutcome.SUCCESS and self.error is not None:
            raise ValueError("successful receipt cannot contain an error")
        if self.outcome is ReceiptOutcome.ERROR and self.error is None:
            raise ValueError("error receipt requires a structured error")
        if (
            self.post_observation is not PostObservationStatus.STABLE
            and self.reconciliation is ReconciliationStatus.ACCEPTED
        ):
            raise ValueError("unstable or unavailable observation cannot be reconciled as accepted")
        if (
            self.post_observation is not PostObservationStatus.STABLE
            and self.reconciliation_error is None
        ):
            raise ValueError("unstable or unavailable observation requires reconciliation error")
        if self.post_observation is not PostObservationStatus.STABLE and not self.settlement_trace:
            raise ValueError("unstable or unavailable observation requires settlement trace")
        if (
            self.outcome is ReceiptOutcome.UNKNOWN
            and self.reconciliation is ReconciliationStatus.ACCEPTED
        ):
            raise ValueError("unknown outcome cannot be reconciled as accepted")
        if self.goal_verification is GoalVerificationStatus.PASSED and (
            self.outcome is not ReceiptOutcome.SUCCESS
            or self.reconciliation is not ReconciliationStatus.ACCEPTED
        ):
            raise ValueError("passed goal verification requires accepted successful evidence")
        if self.capability != "attack" and self.combat is not None:
            raise ValueError("only attack receipts may contain combat terminal evidence")
        if (
            self.capability == "attack"
            and self.outcome is ReceiptOutcome.SUCCESS
            and self.combat is None
        ):
            raise ValueError("successful attack receipt requires combat terminal evidence")
        return self


class ActionInspectionState(StrEnum):
    NOT_FOUND = "not_found"
    ACCEPTED = "accepted"
    RUNNING = "running"
    TERMINAL = "terminal"


class ActionStatus(V2ContractModel):
    schema_version: Literal["2"] = "2"
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    state: ActionInspectionState
    request_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    receipt: ActionReceipt | None = None
    retained_until_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _receipt_matches_state(self) -> ActionStatus:
        if self.state is ActionInspectionState.TERMINAL and self.receipt is None:
            raise ValueError("terminal action status requires the original receipt")
        if self.state is not ActionInspectionState.TERMINAL and self.receipt is not None:
            raise ValueError("non-terminal action status cannot contain a receipt")
        return self


class CancellationAck(V2ContractModel):
    schema_version: Literal["2"] = "2"
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    correlation_id: str = Field(min_length=1, max_length=128)
    accepted: bool
    accepted_at_ms: int = Field(ge=0)


class RuntimeHealth(V2ContractModel):
    schema_version: Literal["2"] = "2"
    ready: bool
    busy: bool
    runtime_instance_id: str = Field(min_length=1, max_length=128)
    active_correlation_id: str | None = None
    last_completed_action_sequence: int = Field(ge=0)
