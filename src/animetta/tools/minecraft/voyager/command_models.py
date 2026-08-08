"""Durable command, controller, projection, and error state contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .budget import BudgetUsage


class CommandState(StrEnum):
    ACCEPTED = "accepted"
    QUEUED = "queued"
    RUNNING = "running"
    RECONCILING = "reconciling"
    SUCCEEDED = "succeeded"
    SUCCEEDED_RECONCILED = "succeeded_reconciled"
    FAILED = "failed"
    FAILED_RECONCILED = "failed_reconciled"
    CANCELLED = "cancelled"
    CANCELLED_RECONCILED = "cancelled_reconciled"
    CANCELLED_BY_STOP = "cancelled_by_stop"
    INTERRUPTED_BEFORE_START = "interrupted_before_start"
    BLOCKED_UNKNOWN = "blocked_unknown"


class ControllerState(StrEnum):
    STARTING = "starting"
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    RECONCILING = "reconciling"
    QUARANTINED = "quarantined"
    CLOSED = "closed"


class CallerWaitState(StrEnum):
    NOT_REQUESTED = "not_requested"
    WAITING = "waiting"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    DISCONNECTED = "disconnected"


class QueueState(StrEnum):
    NOT_ADMITTED = "not_admitted"
    ELIGIBLE = "eligible"
    DISPATCHED = "dispatched"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ExecutionState(StrEnum):
    NOT_STARTED = "not_started"
    EXECUTING = "executing"
    CANCELLING = "cancelling"
    RECONCILING = "reconciling"
    TERMINAL = "terminal"


TERMINAL_COMMAND_STATES = frozenset(
    {
        CommandState.SUCCEEDED,
        CommandState.SUCCEEDED_RECONCILED,
        CommandState.FAILED,
        CommandState.FAILED_RECONCILED,
        CommandState.CANCELLED,
        CommandState.CANCELLED_RECONCILED,
        CommandState.CANCELLED_BY_STOP,
        CommandState.INTERRUPTED_BEFORE_START,
        CommandState.BLOCKED_UNKNOWN,
    }
)

_TRANSITIONS = {
    CommandState.ACCEPTED: {CommandState.QUEUED, CommandState.CANCELLED_BY_STOP},
    CommandState.QUEUED: {
        CommandState.RUNNING,
        CommandState.CANCELLED_BY_STOP,
        CommandState.INTERRUPTED_BEFORE_START,
        CommandState.FAILED,
    },
    CommandState.RUNNING: {
        CommandState.RECONCILING,
        CommandState.SUCCEEDED,
        CommandState.SUCCEEDED_RECONCILED,
        CommandState.FAILED,
        CommandState.FAILED_RECONCILED,
        CommandState.CANCELLED,
        CommandState.CANCELLED_RECONCILED,
        CommandState.BLOCKED_UNKNOWN,
    },
    CommandState.RECONCILING: {
        CommandState.SUCCEEDED,
        CommandState.SUCCEEDED_RECONCILED,
        CommandState.FAILED,
        CommandState.FAILED_RECONCILED,
        CommandState.CANCELLED,
        CommandState.CANCELLED_RECONCILED,
        CommandState.BLOCKED_UNKNOWN,
    },
    CommandState.BLOCKED_UNKNOWN: {CommandState.RECONCILING},
}


def validate_transition(current: CommandState, target: CommandState) -> bool:
    if target not in _TRANSITIONS.get(current, set()):
        raise ValueError(f"illegal command transition: {current.value} -> {target.value}")
    return True


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CancellationFact(_FrozenModel):
    requested_at_ms: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)
    stop_barrier_id: str | None = None
    signal_accepted: bool | None = None


class ControlPlaneError(_FrozenModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    message: str
    phase: str
    outcome_known: bool
    world_may_have_changed: bool
    caller_may_resubmit: bool
    operator_action: str
    details: dict[str, Any] = Field(default_factory=dict)


class CommandResult(_FrozenModel):
    command_id: str
    state: CommandState
    output: dict[str, Any] = Field(default_factory=dict)
    receipt_ids: tuple[str, ...] = ()
    learning_evidence_eligible: bool = False
    error: ControlPlaneError | None = None


class CommandProjection(_FrozenModel):
    projection_version: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    command_id: str
    caller_scope: str
    request_id: str
    state: CommandState
    caller_wait: CallerWaitState = CallerWaitState.NOT_REQUESTED
    queue: QueueState = QueueState.NOT_ADMITTED
    execution: ExecutionState = ExecutionState.NOT_STARTED
    active_phase: str = ""
    budget_usage: BudgetUsage = BudgetUsage()
    recovery_state: str = ""
    error: ControlPlaneError | None = None
