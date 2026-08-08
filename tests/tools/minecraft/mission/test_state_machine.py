from __future__ import annotations

from importlib import import_module

import pytest

from animetta.tools.minecraft.mission.repository import (
    MissionStatus,
    ObjectiveRecord,
    ObjectiveStatus,
)

from .test_models import _mission_payload


def _state_machine_module():
    return import_module("animetta.tools.minecraft.mission.state_machine")


MISSION_TRANSITIONS = {
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

OBJECTIVE_TRANSITIONS = {
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


def test_mission_transition_function_matches_the_reference_state_model() -> None:
    state_machine = _state_machine_module()

    for current in MissionStatus:
        for target in MissionStatus:
            expected = target in MISSION_TRANSITIONS.get(current, set())
            if expected:
                assert state_machine.validate_mission_transition(current, target)
            else:
                with pytest.raises(ValueError, match="illegal mission transition"):
                    state_machine.validate_mission_transition(current, target)


def test_objective_transition_function_matches_the_minimal_reference_model() -> None:
    state_machine = _state_machine_module()

    for current in ObjectiveStatus:
        for target in ObjectiveStatus:
            expected = target in OBJECTIVE_TRANSITIONS.get(current, set())
            if expected:
                assert state_machine.validate_objective_transition(current, target)
            else:
                with pytest.raises(ValueError, match="illegal objective transition"):
                    state_machine.validate_objective_transition(current, target)


def test_readiness_admission_command_phase_and_verification_are_derived() -> None:
    state_machine = _state_machine_module()
    mission = state_machine.MissionSpec.model_validate(_mission_payload())
    objective = ObjectiveRecord(
        mission_id=mission.mission_id,
        ordinal=1,
        objective=mission.objectives[1],
    )

    blocked = state_machine.derive_objective_projection(
        objective,
        completed_objective_ids=frozenset(),
    )
    ready = state_machine.derive_objective_projection(
        objective,
        completed_objective_ids=frozenset({"fight-zombie"}),
    )
    active = state_machine.derive_objective_projection(
        objective.model_copy(update={"status": ObjectiveStatus.ACTIVE}),
        completed_objective_ids=frozenset({"fight-zombie"}),
        proposal_outcome="accepted",
        command_state="running",
        verification_outcome="pending",
    )
    completed = state_machine.derive_objective_projection(
        objective.model_copy(update={"status": ObjectiveStatus.COMPLETED}),
        completed_objective_ids=frozenset({"fight-zombie"}),
        proposal_outcome="accepted",
        command_state="succeeded",
        verification_outcome="verified",
    )

    assert (blocked.ready, blocked.readiness) == (False, "blocked_dependencies")
    assert (ready.ready, ready.readiness) == (True, "ready")
    assert (active.admission, active.command_phase, active.verification) == (
        "accepted",
        "running",
        "pending",
    )
    assert (completed.readiness, completed.command_phase, completed.verification) == (
        "terminal",
        "terminal",
        "verified",
    )
    assert not {
        "ready",
        "readiness",
        "proposal_outcome",
        "command_phase",
        "verification",
    }.intersection(ObjectiveRecord.model_fields)
