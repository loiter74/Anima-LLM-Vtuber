from __future__ import annotations

from importlib import import_module

from animetta.tools.minecraft.mission.coordinator import MissionCoordinator
from animetta.tools.minecraft.mission.models import GoalAdmissionDecision, MissionSpec
from animetta.tools.minecraft.mission.repository import (
    InMemoryMissionRepository,
    MissionEvidenceLink,
)
from animetta.tools.minecraft.voyager.budget import BudgetAccount
from animetta.tools.minecraft.voyager.journal import InMemoryCommandJournal

from .test_admission import _proposal
from .test_coordinator import _fixed_mission
from .test_models import _mission_payload


def _projection_module():
    return import_module("animetta.tools.minecraft.mission.projection")


async def test_projection_aggregates_derived_objective_proposal_budget_and_evidence() -> None:
    module = _projection_module()
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    mission = _fixed_mission()
    coordinator = MissionCoordinator(repository=repository, journal=journal)
    await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1_000,
    )
    proposal = _proposal()
    decision = GoalAdmissionDecision(
        proposal_id=proposal.proposal_id,
        outcome="accepted",
        reason_code="ADMITTED",
        reserved_budget=proposal.conservative_cost,
    )
    await repository.save_proposal(proposal, decision, occurred_at_ms=1_010)
    account = BudgetAccount(limit=mission.budget).reserve(
        proposal.proposal_id, proposal.conservative_cost
    )
    await repository.save_budget(mission.mission_id, account, updated_at_ms=1_011)
    await repository.link_evidence(
        MissionEvidenceLink(
            link_id="evidence-001",
            mission_id=mission.mission_id,
            objective_id="fight-zombie",
            evidence_kind="observation",
            evidence_ref="observation:obs-001",
            attributable=True,
            linked_at_ms=1_012,
        )
    )
    service = module.MissionProjectionService(repository=repository, journal=journal)

    page = await service.read(caller_scope="conversation:user-001", limit=20)

    assert page.next_cursor is None
    assert len(page.missions) == 1
    projection = page.missions[0]
    assert projection.mission_id == mission.mission_id
    assert projection.caller_scope == "conversation:user-001"
    assert projection.status == "running"
    assert projection.objectives[0].readiness == "active"
    assert projection.objectives[0].command_phase == "queued"
    assert projection.objectives[1].readiness == "blocked_dependencies"
    assert projection.proposal_counts == {"accepted": 1}
    assert projection.budget_reserved.max_actions == 2
    assert projection.budget_remaining.max_actions == 18
    assert projection.evidence_refs == ("observation:obs-001",)
    assert projection.recovery_state == "none"


async def test_projection_is_caller_scoped_and_cursor_paginated() -> None:
    module = _projection_module()
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    base = _mission_payload()
    base["completion_predicates"] = []
    base["autonomy"] = {"mode": "off"}
    for index, caller in enumerate(
        ("conversation:user-001", "conversation:user-001", "conversation:other")
    ):
        payload = dict(base)
        payload["mission_id"] = f"mission-page-{index}"
        await repository.create_mission(
            caller_scope=caller,
            request_id=f"request-page-{index}",
            spec=MissionSpec.model_validate(payload),
            occurred_at_ms=2_000 + index,
        )
    service = module.MissionProjectionService(repository=repository, journal=journal)

    first = await service.read(caller_scope="conversation:user-001", limit=1)
    second = await service.read(
        caller_scope="conversation:user-001", limit=1, cursor=first.next_cursor
    )

    assert [item.mission_id for item in first.missions] == ["mission-page-0"]
    assert first.next_cursor is not None
    assert [item.mission_id for item in second.missions] == ["mission-page-1"]
    assert second.next_cursor is None
    assert all(item.caller_scope == "conversation:user-001" for item in second.missions)
