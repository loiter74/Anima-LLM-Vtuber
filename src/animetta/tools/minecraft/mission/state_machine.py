"""Minimal durable mission states and derived execution projections."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .models import MissionSpec
from .repository import MissionStatus, ObjectiveRecord, ObjectiveStatus

ObjectiveReadiness = Literal["blocked_dependencies", "ready", "active", "terminal"]
ObjectiveCommandPhase = Literal["none", "queued", "running", "reconciling", "terminal"]
ObjectiveVerification = Literal["not_started", "pending", "verified", "failed", "unknown"]

_MISSION_TRANSITIONS = {
    MissionStatus.ACCEPTED: {MissionStatus.PLANNING, MissionStatus.CANCELLED},
    MissionStatus.PLANNING: {
        MissionStatus.RUNNING,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
        MissionStatus.BLOCKED_UNKNOWN,
    },
    MissionStatus.RUNNING: {
        MissionStatus.WAITING_EVIDENCE,
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
        MissionStatus.BLOCKED_UNKNOWN,
    },
    MissionStatus.WAITING_EVIDENCE: {
        MissionStatus.RUNNING,
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.CANCELLED,
        MissionStatus.BLOCKED_UNKNOWN,
    },
}
_OBJECTIVE_TRANSITIONS = {
    ObjectiveStatus.PENDING: {
        ObjectiveStatus.ACTIVE,
        ObjectiveStatus.SKIPPED,
        ObjectiveStatus.CANCELLED,
        ObjectiveStatus.BLOCKED_UNKNOWN,
    },
    ObjectiveStatus.ACTIVE: {
        ObjectiveStatus.COMPLETED,
        ObjectiveStatus.FAILED,
        ObjectiveStatus.CANCELLED,
        ObjectiveStatus.BLOCKED_UNKNOWN,
    },
}
_TERMINAL_OBJECTIVE_STATES = frozenset(
    {
        ObjectiveStatus.COMPLETED,
        ObjectiveStatus.FAILED,
        ObjectiveStatus.SKIPPED,
        ObjectiveStatus.CANCELLED,
        ObjectiveStatus.BLOCKED_UNKNOWN,
    }
)
_TERMINAL_COMMAND_STATES = frozenset(
    {
        "succeeded",
        "succeeded_reconciled",
        "failed",
        "failed_reconciled",
        "cancelled",
        "cancelled_reconciled",
        "cancelled_by_stop",
        "interrupted_before_start",
        "blocked_unknown",
    }
)


def validate_mission_transition(current: MissionStatus, target: MissionStatus) -> bool:
    """Reject mission lifecycle edges outside the closed state model."""

    if target not in _MISSION_TRANSITIONS.get(current, set()):
        raise ValueError(f"illegal mission transition: {current.value} -> {target.value}")
    return True


def validate_objective_transition(current: ObjectiveStatus, target: ObjectiveStatus) -> bool:
    """Reject objective lifecycle edges outside the minimal persistent model."""

    if target not in _OBJECTIVE_TRANSITIONS.get(current, set()):
        raise ValueError(f"illegal objective transition: {current.value} -> {target.value}")
    return True


class ObjectiveProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    objective_id: str
    persisted_status: ObjectiveStatus
    ready: bool
    readiness: ObjectiveReadiness
    unmet_dependencies: tuple[str, ...] = ()
    admission: Literal["none", "accepted", "rejected", "deferred"] = "none"
    command_phase: ObjectiveCommandPhase = "none"
    verification: ObjectiveVerification = "not_started"


def _command_phase(command_state: str | None) -> ObjectiveCommandPhase:
    if command_state is None:
        return "none"
    if command_state in {"accepted", "queued"}:
        return "queued"
    if command_state == "running":
        return "running"
    if command_state == "reconciling":
        return "reconciling"
    if command_state in _TERMINAL_COMMAND_STATES:
        return "terminal"
    raise ValueError(f"unknown command state: {command_state}")


def derive_objective_projection(
    objective: ObjectiveRecord,
    *,
    completed_objective_ids: frozenset[str],
    proposal_outcome: Literal["accepted", "rejected", "deferred"] | None = None,
    command_state: str | None = None,
    verification_outcome: Literal["pending", "verified", "failed", "unknown"] | None = None,
) -> ObjectiveProjection:
    """Project transient phases solely from persistent facts and linked records."""

    dependencies = frozenset(objective.objective.dependencies)
    unmet = tuple(sorted(dependencies - completed_objective_ids))
    if objective.status in _TERMINAL_OBJECTIVE_STATES:
        readiness: ObjectiveReadiness = "terminal"
        ready = False
    elif objective.status is ObjectiveStatus.ACTIVE:
        readiness = "active"
        ready = False
    elif unmet:
        readiness = "blocked_dependencies"
        ready = False
    else:
        readiness = "ready"
        ready = True
    if verification_outcome is None:
        if objective.status is ObjectiveStatus.COMPLETED:
            verification: ObjectiveVerification = "verified"
        elif objective.status in {ObjectiveStatus.FAILED, ObjectiveStatus.CANCELLED}:
            verification = "failed"
        elif objective.status is ObjectiveStatus.BLOCKED_UNKNOWN:
            verification = "unknown"
        else:
            verification = "not_started"
    else:
        verification = verification_outcome
    return ObjectiveProjection(
        objective_id=objective.objective.objective_id,
        persisted_status=objective.status,
        ready=ready,
        readiness=readiness,
        unmet_dependencies=unmet,
        admission=proposal_outcome or "none",
        command_phase=_command_phase(command_state),
        verification=verification,
    )


__all__ = [
    "MissionSpec",
    "ObjectiveProjection",
    "derive_objective_projection",
    "validate_mission_transition",
    "validate_objective_transition",
]
