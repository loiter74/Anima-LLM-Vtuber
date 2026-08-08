"""Caller-scoped aggregate mission status projections."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.minecraft.voyager.budget import BudgetUsage, ExecutionBudget
from animetta.tools.minecraft.voyager.journal import CommandJournal

from .repository import MissionRepository, MissionSnapshot, MissionStatus
from .state_machine import ObjectiveProjection, derive_objective_projection


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProposalProjection(_FrozenModel):
    proposal_id: str
    origin: str
    parent_objective_id: str | None = None
    outcome: Literal["accepted", "rejected", "deferred"]
    reason_code: str


class MissionProjection(_FrozenModel):
    projection_version: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    mission_id: str
    caller_scope: str
    request_id: str
    status: MissionStatus
    objectives: tuple[ObjectiveProjection, ...]
    proposals: tuple[ProposalProjection, ...] = ()
    proposal_counts: dict[str, int] = Field(default_factory=dict)
    budget_used: BudgetUsage = BudgetUsage()
    budget_reserved: BudgetUsage = BudgetUsage()
    budget_remaining: ExecutionBudget
    evidence_refs: tuple[str, ...] = ()
    recovery_state: Literal["none", "reconciling", "blocked_unknown"] = "none"
    presentation_artifact_count: int = Field(default=0, ge=0)


class MissionProjectionPage(_FrozenModel):
    missions: tuple[MissionProjection, ...]
    next_cursor: str | None = None


class MissionProjectionService:
    """Read-only join of mission records and the authoritative command journal."""

    def __init__(self, *, repository: MissionRepository, journal: CommandJournal) -> None:
        self._repository = repository
        self._journal = journal

    @staticmethod
    def _linked_command(snapshot: MissionSnapshot, objective_id: str) -> str | None:
        for transition in reversed(snapshot.transitions):
            if transition.objective_id == objective_id:
                command_id = transition.details.get("command_id")
                if isinstance(command_id, str):
                    return command_id
        return None

    async def _project(self, snapshot: MissionSnapshot) -> MissionProjection:
        completed = frozenset(
            record.objective.objective_id
            for record in snapshot.objectives
            if record.status.value == "completed"
        )
        proposal_by_parent = {
            stored.proposal.parent_objective_id: stored.decision.outcome
            for stored in snapshot.proposals
            if stored.proposal.parent_objective_id is not None
        }
        objective_projections: list[ObjectiveProjection] = []
        command_states: list[str] = []
        for objective in snapshot.objectives:
            objective_id = objective.objective.objective_id
            command_id = self._linked_command(snapshot, objective_id)
            command = await self._journal.get_command(command_id) if command_id else None
            command_state = command.state.value if command else None
            if command_state:
                command_states.append(command_state)
            objective_projections.append(
                derive_objective_projection(
                    objective,
                    completed_objective_ids=completed,
                    proposal_outcome=proposal_by_parent.get(objective_id),
                    command_state=command_state,
                )
            )
        proposals = tuple(
            ProposalProjection(
                proposal_id=stored.proposal.proposal_id,
                origin=stored.proposal.origin,
                parent_objective_id=stored.proposal.parent_objective_id,
                outcome=stored.decision.outcome,
                reason_code=stored.decision.reason_code,
            )
            for stored in snapshot.proposals
        )
        counts: dict[str, int] = dict(Counter(proposal.outcome for proposal in proposals))
        account = snapshot.budget
        if account is None:
            used = BudgetUsage()
            reserved = BudgetUsage()
            remaining = snapshot.mission.spec.budget
        else:
            used = account.used
            reserved = account.reserved
            remaining = account.remaining
        if snapshot.mission.status is MissionStatus.BLOCKED_UNKNOWN:
            recovery_state: Literal["none", "reconciling", "blocked_unknown"] = "blocked_unknown"
        elif "reconciling" in command_states:
            recovery_state = "reconciling"
        else:
            recovery_state = "none"
        projection_version = (
            snapshot.mission.version
            + sum(objective.version for objective in snapshot.objectives)
            + len(snapshot.transitions)
            + len(snapshot.proposals)
            + len(snapshot.evidence_links)
        )
        return MissionProjection(
            projection_version=projection_version,
            updated_at_ms=snapshot.mission.updated_at_ms,
            mission_id=snapshot.mission.spec.mission_id,
            caller_scope=snapshot.mission.caller_scope,
            request_id=snapshot.mission.request_id,
            status=snapshot.mission.status,
            objectives=tuple(objective_projections),
            proposals=proposals,
            proposal_counts=counts,
            budget_used=used,
            budget_reserved=reserved,
            budget_remaining=remaining,
            evidence_refs=tuple(link.evidence_ref for link in snapshot.evidence_links),
            recovery_state=recovery_state,
            presentation_artifact_count=len(snapshot.presentation_artifacts),
        )

    async def read(
        self,
        *,
        caller_scope: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> MissionProjectionPage:
        """Return one bounded page containing only the trusted caller scope."""

        missions, next_cursor = await self._repository.list_missions(
            caller_scope, limit=limit, cursor=cursor
        )
        return MissionProjectionPage(
            missions=tuple(
                [
                    await self._project(await self._repository.snapshot(mission.spec.mission_id))
                    for mission in missions
                ]
            ),
            next_cursor=next_cursor,
        )
