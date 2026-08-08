"""Transition-driven mission coordination above the single Voyager scheduler."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import RuntimeManifest, canonical_json_hash
from animetta.tools.minecraft.discovery.exploration import (
    ExplorationInput,
    ExplorationProposer,
)
from animetta.tools.minecraft.voyager.budget import BudgetAccount, BudgetUsage
from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.journal import CommandDraft, CommandJournal

from .admission import AdmissionContext, GoalAdmission
from .models import MissionObjective, MissionSpec
from .repository import (
    MissionEvidenceLink,
    MissionRepository,
    MissionStatus,
    ObjectiveRecord,
    ObjectiveStatus,
)
from .verifier import MissionEvidenceSnapshot, MissionVerifier


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MissionAdvanceResult(_FrozenModel):
    mission_id: str
    mission_status: MissionStatus
    idempotency_reused: bool = False
    eligible_objective_id: str | None = None
    eligible_command_id: str | None = None
    exploration_outcome: str | None = None
    proposal_id: str | None = None
    admission_outcome: str | None = None
    completion_evidence_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class VerifiedChildTransition(_FrozenModel):
    mission_id: str
    objective_id: str
    command_id: str
    command_state: Literal[
        "succeeded",
        "succeeded_reconciled",
        "failed",
        "failed_reconciled",
        "cancelled",
        "cancelled_reconciled",
        "cancelled_by_stop",
        "interrupted_before_start",
        "blocked_unknown",
    ]
    verification: Literal["verified", "failed", "unknown"]
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    actual_budget: BudgetUsage = BudgetUsage()
    occurred_at_ms: int = Field(ge=0)


def _effective_budget(objective: ObjectiveRecord, spec: MissionSpec) -> dict[str, object]:
    parent = spec.budget.model_dump(mode="json")
    cost = objective.objective.budget.model_dump(mode="json")
    for field in (
        "max_actions",
        "max_strategy_attempts",
        "max_travel_distance",
        "max_blocks_changed",
        "max_damage_taken",
        "resource_consumption",
    ):
        parent[field] = cost[field]
    return parent


def _initial_budget_account(spec: MissionSpec) -> BudgetAccount:
    account = BudgetAccount(limit=spec.budget)
    for objective in spec.objectives:
        account = account.reserve(f"objective:{objective.objective_id}", objective.budget)
    return account


class MissionCoordinator:
    """Advance durable mission state without claiming or executing gameplay."""

    def __init__(self, *, repository: MissionRepository, journal: CommandJournal) -> None:
        self._repository = repository
        self._journal = journal

    async def submit(
        self,
        *,
        caller_scope: str,
        request_id: str,
        spec: MissionSpec,
        occurred_at_ms: int,
    ) -> MissionAdvanceResult:
        mission, reused = await self._repository.create_mission(
            caller_scope=caller_scope,
            request_id=request_id,
            spec=spec,
            occurred_at_ms=occurred_at_ms,
        )
        if reused:
            snapshot = await self._repository.snapshot(spec.mission_id)
            active = next(
                (item for item in snapshot.objectives if item.status is ObjectiveStatus.ACTIVE),
                None,
            )
            command_id = self._linked_command(snapshot.transitions, active)
            return MissionAdvanceResult(
                mission_id=spec.mission_id,
                mission_status=snapshot.mission.status,
                idempotency_reused=True,
                eligible_objective_id=(active.objective.objective_id if active else None),
                eligible_command_id=command_id,
            )
        await self._repository.save_budget(
            spec.mission_id,
            _initial_budget_account(spec),
            updated_at_ms=occurred_at_ms,
        )
        mission = await self._repository.transition_mission(
            spec.mission_id,
            expected_version=mission.version,
            target=MissionStatus.PLANNING,
            reason_code="MISSION_ADMITTED",
            actor="mission-coordinator",
            occurred_at_ms=occurred_at_ms,
        )
        return await self._advance(
            mission.spec.mission_id,
            caller_scope=caller_scope,
            occurred_at_ms=occurred_at_ms,
        )

    async def consider_exploration(
        self,
        mission_id: str,
        *,
        exploration: ExplorationInput,
        proposer: ExplorationProposer,
        manifest: RuntimeManifest,
        occurred_at_ms: int,
        runtime_quarantined: bool = False,
    ) -> MissionAdvanceResult:
        """Admit at most one observation-driven child through the shared policy path."""

        snapshot = await self._repository.snapshot(mission_id)
        active = next(
            (item for item in snapshot.objectives if item.status is ObjectiveStatus.ACTIVE),
            None,
        )

        def current_result(
            *,
            exploration_outcome: str,
            proposal_id: str | None = None,
            admission_outcome: str | None = None,
        ) -> MissionAdvanceResult:
            return MissionAdvanceResult(
                mission_id=mission_id,
                mission_status=snapshot.mission.status,
                eligible_objective_id=(
                    active.objective.objective_id if active is not None else None
                ),
                eligible_command_id=self._linked_command(snapshot.transitions, active),
                exploration_outcome=exploration_outcome,
                proposal_id=proposal_id,
                admission_outcome=admission_outcome,
            )

        if exploration.mission_id != mission_id:
            raise ValueError("exploration mission does not match coordinator mission")
        if snapshot.mission.spec.autonomy.mode == "off":
            return current_result(exploration_outcome="AUTONOMY_OFF")
        if snapshot.mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
            MissionStatus.BLOCKED_UNKNOWN,
        }:
            return current_result(exploration_outcome="MISSION_TERMINAL")

        stored_goal_hashes = frozenset(
            item.proposal.goal.canonical_hash for item in snapshot.proposals
        )
        consumed_observations = frozenset(
            evidence_ref
            for item in snapshot.proposals
            for evidence_ref in item.proposal.evidence_refs
            if evidence_ref.startswith("observation:")
        )
        decision = proposer.propose(
            exploration.model_copy(
                update={
                    "proposed_goal_hashes": (exploration.proposed_goal_hashes | stored_goal_hashes),
                    "consumed_observation_refs": (
                        exploration.consumed_observation_refs | consumed_observations
                    ),
                }
            )
        )
        if decision.proposal is None:
            return current_result(exploration_outcome=decision.outcome)

        accepted_records = tuple(
            item for item in snapshot.proposals if item.decision.outcome == "accepted"
        )
        completed = frozenset(
            item.objective.objective_id
            for item in snapshot.objectives
            if item.status is ObjectiveStatus.COMPLETED
        )
        budget = snapshot.budget or _initial_budget_account(snapshot.mission.spec)
        admission = GoalAdmission().admit(
            decision.proposal,
            AdmissionContext(
                mission=snapshot.mission.spec,
                manifest=manifest,
                budget_account=budget,
                completed_objective_ids=completed,
                seen_proposal_ids=frozenset(
                    item.proposal.proposal_id for item in snapshot.proposals
                ),
                admitted_goal_hashes=frozenset(
                    item.proposal.goal.canonical_hash for item in accepted_records
                ),
                admitted_child_count=sum(
                    item.proposal.origin in {"curriculum", "recovery"} for item in accepted_records
                ),
                runtime_quarantined=runtime_quarantined,
            ),
        )
        await self._repository.save_proposal(
            decision.proposal,
            admission.decision,
            occurred_at_ms=occurred_at_ms,
        )
        await self._repository.save_budget(
            mission_id,
            admission.context.budget_account,
            updated_at_ms=occurred_at_ms,
        )
        if admission.decision.outcome != "accepted":
            return current_result(
                exploration_outcome=decision.outcome,
                proposal_id=decision.proposal.proposal_id,
                admission_outcome=admission.decision.outcome,
            )

        child_id = f"child-{canonical_json_hash(decision.proposal.canonical_payload())[:24]}"
        dependencies = (
            (decision.proposal.parent_objective_id,)
            if decision.proposal.parent_objective_id is not None
            else ()
        )
        await self._repository.append_objective(
            mission_id,
            MissionObjective(
                objective_id=child_id,
                goal=decision.proposal.goal,
                dependencies=dependencies,
                required=True,
                priority=40,
                budget=decision.proposal.conservative_cost,
            ),
            reason_code="AUTONOMOUS_PROPOSAL_ADMITTED",
            actor="mission-coordinator",
            occurred_at_ms=occurred_at_ms,
            evidence_refs=decision.proposal.evidence_refs,
        )
        advanced = await self._advance(
            mission_id,
            caller_scope=snapshot.mission.caller_scope,
            occurred_at_ms=occurred_at_ms,
        )
        return advanced.model_copy(
            update={
                "exploration_outcome": decision.outcome,
                "proposal_id": decision.proposal.proposal_id,
                "admission_outcome": admission.decision.outcome,
            }
        )

    @staticmethod
    def _linked_command(transitions: tuple, objective: ObjectiveRecord | None) -> str | None:
        if objective is None:
            return None
        objective_id = objective.objective.objective_id
        for transition in reversed(transitions):
            if transition.objective_id == objective_id:
                command_id = transition.details.get("command_id")
                if isinstance(command_id, str):
                    return command_id
        return None

    async def _advance(
        self,
        mission_id: str,
        *,
        caller_scope: str,
        occurred_at_ms: int,
    ) -> MissionAdvanceResult:
        snapshot = await self._repository.snapshot(mission_id)
        active = next(
            (item for item in snapshot.objectives if item.status is ObjectiveStatus.ACTIVE),
            None,
        )
        if active is not None:
            return MissionAdvanceResult(
                mission_id=mission_id,
                mission_status=snapshot.mission.status,
                eligible_objective_id=active.objective.objective_id,
                eligible_command_id=self._linked_command(snapshot.transitions, active),
            )
        completed = frozenset(
            item.objective.objective_id
            for item in snapshot.objectives
            if item.status is ObjectiveStatus.COMPLETED
        )
        ready = [
            item
            for item in snapshot.objectives
            if item.status is ObjectiveStatus.PENDING
            and set(item.objective.dependencies).issubset(completed)
        ]
        if not ready:
            required_complete = all(
                (not item.objective.required) or item.status is ObjectiveStatus.COMPLETED
                for item in snapshot.objectives
            )
            if required_complete:
                target = (
                    MissionStatus.WAITING_EVIDENCE
                    if snapshot.mission.spec.completion_predicates
                    else MissionStatus.COMPLETED
                )
                if snapshot.mission.status is not target:
                    mission = await self._repository.transition_mission(
                        mission_id,
                        expected_version=snapshot.mission.version,
                        target=target,
                        reason_code=(
                            "MISSION_PREDICATES_PENDING"
                            if target is MissionStatus.WAITING_EVIDENCE
                            else "MISSION_VERIFIED_COMPLETE"
                        ),
                        actor="mission-coordinator",
                        occurred_at_ms=occurred_at_ms,
                    )
                else:
                    mission = snapshot.mission
            else:
                mission = snapshot.mission
            return MissionAdvanceResult(
                mission_id=mission_id,
                mission_status=mission.status,
            )
        objective = sorted(ready, key=lambda item: (-item.objective.priority, item.ordinal))[0]
        payload = {
            "mission_id": mission_id,
            "objective_id": objective.objective.objective_id,
            "goal": objective.objective.goal.model_dump(mode="json", exclude_none=True),
            "execution_policy": snapshot.mission.spec.execution.model_dump(mode="json"),
        }
        command_id = (
            f"mission-{mission_id}-{objective.objective.objective_id}-v{objective.version + 1}"
        )
        request_id = f"{mission_id}:{objective.objective.objective_id}:v{objective.version + 1}"
        effective_budget = _effective_budget(objective, snapshot.mission.spec)
        command, _ = await self._journal.create_command(
            CommandDraft(
                command_id=command_id,
                caller_scope=caller_scope,
                request_id=request_id,
                request_hash=canonical_json_hash(payload),
                kind="execute",
                mode="mission",
                payload=payload,
                requested_budget=objective.objective.budget.model_dump(mode="json"),
                effective_budget=effective_budget,
                accepted_at_ms=occurred_at_ms,
                queue_deadline_ms=occurred_at_ms + snapshot.mission.spec.budget.queue_timeout_ms,
                execution_deadline_ms=occurred_at_ms
                + snapshot.mission.spec.budget.execution_timeout_ms,
            )
        )
        await self._repository.transition_objective(
            mission_id,
            objective.objective.objective_id,
            expected_version=objective.version,
            target=ObjectiveStatus.ACTIVE,
            reason_code="LEAF_COMMAND_ELIGIBLE",
            actor="mission-coordinator",
            occurred_at_ms=occurred_at_ms,
            details={"command_id": command.command_id},
        )
        mission = snapshot.mission
        if mission.status in {MissionStatus.PLANNING, MissionStatus.WAITING_EVIDENCE}:
            mission = await self._repository.transition_mission(
                mission_id,
                expected_version=mission.version,
                target=MissionStatus.RUNNING,
                reason_code="LEAF_COMMAND_ELIGIBLE",
                actor="mission-coordinator",
                occurred_at_ms=occurred_at_ms,
                details={"command_id": command.command_id},
            )
        return MissionAdvanceResult(
            mission_id=mission_id,
            mission_status=mission.status,
            eligible_objective_id=objective.objective.objective_id,
            eligible_command_id=command.command_id,
        )

    async def advance_from_committed_evidence(
        self, mission_id: str, *, occurred_at_ms: int
    ) -> MissionAdvanceResult:
        """Advance only a nonterminal mission after new durable evidence is committed."""

        snapshot = await self._repository.snapshot(mission_id)
        if snapshot.mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
            MissionStatus.BLOCKED_UNKNOWN,
        }:
            return MissionAdvanceResult(
                mission_id=mission_id,
                mission_status=snapshot.mission.status,
            )
        return await self._advance(
            mission_id,
            caller_scope=snapshot.mission.caller_scope,
            occurred_at_ms=occurred_at_ms,
        )

    async def verify_completion(
        self,
        mission_id: str,
        *,
        evidence: MissionEvidenceSnapshot,
        occurred_at_ms: int,
    ) -> MissionAdvanceResult:
        """Commit completion only after the independent mission verifier passes."""

        snapshot = await self._repository.snapshot(mission_id)
        if snapshot.mission.status is MissionStatus.COMPLETED:
            return MissionAdvanceResult(
                mission_id=mission_id,
                mission_status=snapshot.mission.status,
            )
        objective_results = {
            item.objective.objective_id: item.status is ObjectiveStatus.COMPLETED
            for item in snapshot.objectives
        }
        verification = MissionVerifier().verify(
            spec=snapshot.mission.spec,
            objective_results=objective_results,
            evidence=evidence,
        )
        if not verification.satisfied:
            return MissionAdvanceResult(
                mission_id=mission_id,
                mission_status=snapshot.mission.status,
                completion_evidence_hash=verification.evidence_hash,
            )
        if snapshot.mission.status is not MissionStatus.WAITING_EVIDENCE:
            raise ValueError("mission is not waiting for completion evidence")
        mission = await self._repository.transition_mission(
            mission_id,
            expected_version=snapshot.mission.version,
            target=MissionStatus.COMPLETED,
            reason_code="MISSION_VERIFIED_COMPLETE",
            actor="mission-verifier",
            occurred_at_ms=occurred_at_ms,
            evidence_refs=(f"mission-verification:{verification.evidence_hash}",),
        )
        return MissionAdvanceResult(
            mission_id=mission_id,
            mission_status=mission.status,
            completion_evidence_hash=verification.evidence_hash,
        )

    async def stop(
        self,
        mission_id: str,
        *,
        request_id: str,
        reason: str,
        occurred_at_ms: int,
    ) -> MissionAdvanceResult:
        """Apply the existing journal stop barrier, then cancel mission projections."""

        snapshot = await self._repository.snapshot(mission_id)
        if snapshot.mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
            MissionStatus.BLOCKED_UNKNOWN,
        }:
            return MissionAdvanceResult(
                mission_id=mission_id,
                mission_status=snapshot.mission.status,
            )
        payload = {"mission_id": mission_id, "reason": reason}
        await self._journal.apply_stop_barrier(
            CommandDraft(
                command_id=f"mission-{mission_id}-stop-{canonical_json_hash(payload)[:16]}",
                caller_scope=snapshot.mission.caller_scope,
                request_id=request_id,
                request_hash=canonical_json_hash(payload),
                kind="stop",
                payload=payload,
                requested_budget={},
                effective_budget={},
                accepted_at_ms=occurred_at_ms,
            ),
            occurred_at_ms=occurred_at_ms,
        )
        for objective in snapshot.objectives:
            if objective.status in {ObjectiveStatus.PENDING, ObjectiveStatus.ACTIVE}:
                await self._repository.transition_objective(
                    mission_id,
                    objective.objective.objective_id,
                    expected_version=objective.version,
                    target=ObjectiveStatus.CANCELLED,
                    reason_code="MISSION_STOP_BARRIER",
                    actor="mission-coordinator",
                    occurred_at_ms=occurred_at_ms,
                    details={"reason": reason},
                )
        mission = await self._repository.transition_mission(
            mission_id,
            expected_version=snapshot.mission.version,
            target=MissionStatus.CANCELLED,
            reason_code="MISSION_STOP_BARRIER",
            actor="mission-coordinator",
            occurred_at_ms=occurred_at_ms,
            details={"reason": reason},
        )
        return MissionAdvanceResult(
            mission_id=mission_id,
            mission_status=mission.status,
        )

    async def recover_startup(
        self, mission_id: str, *, occurred_at_ms: int
    ) -> MissionAdvanceResult:
        """Reconcile startup state without replaying an active or ambiguous child."""

        await self._journal.recover_startup(occurred_at_ms=occurred_at_ms)
        snapshot = await self._repository.snapshot(mission_id)
        if snapshot.mission.status in {
            MissionStatus.COMPLETED,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
            MissionStatus.BLOCKED_UNKNOWN,
        }:
            return MissionAdvanceResult(
                mission_id=mission_id,
                mission_status=snapshot.mission.status,
            )
        active = next(
            (item for item in snapshot.objectives if item.status is ObjectiveStatus.ACTIVE),
            None,
        )
        command_id = self._linked_command(snapshot.transitions, active)
        command = await self._journal.get_command(command_id) if command_id else None
        if active is not None:
            await self._repository.transition_objective(
                mission_id,
                active.objective.objective_id,
                expected_version=active.version,
                target=ObjectiveStatus.BLOCKED_UNKNOWN,
                reason_code="STARTUP_CHILD_AMBIGUOUS",
                actor="mission-coordinator",
                occurred_at_ms=occurred_at_ms,
                details={
                    "command_id": command_id,
                    "command_state": command.state.value if command else "missing",
                },
            )
        mission = await self._repository.transition_mission(
            mission_id,
            expected_version=snapshot.mission.version,
            target=MissionStatus.BLOCKED_UNKNOWN,
            reason_code="STARTUP_CHILD_AMBIGUOUS",
            actor="mission-coordinator",
            occurred_at_ms=occurred_at_ms,
            details={
                "command_id": command_id,
                "command_state": command.state.value if command else "missing",
            },
        )
        return MissionAdvanceResult(
            mission_id=mission_id,
            mission_status=mission.status,
        )

    async def on_child_transition(
        self, transition: VerifiedChildTransition
    ) -> MissionAdvanceResult:
        snapshot = await self._repository.snapshot(transition.mission_id)
        objective = next(
            item
            for item in snapshot.objectives
            if item.objective.objective_id == transition.objective_id
        )
        if objective.status is not ObjectiveStatus.ACTIVE:
            raise ValueError("child objective is not active")
        linked_command = self._linked_command(snapshot.transitions, objective)
        if linked_command != transition.command_id:
            raise ValueError("child command does not match objective")
        command = await self._journal.get_command(transition.command_id)
        if command is None or command.state.value != transition.command_state:
            raise ValueError("child transition is not journal-verified")

        budget = snapshot.budget or _initial_budget_account(snapshot.mission.spec)
        fixed_reservation = f"objective:{transition.objective_id}"
        if fixed_reservation in budget.reservations:
            reservation_id = fixed_reservation
        else:
            proposal_reservations = [
                stored.proposal.proposal_id
                for stored in snapshot.proposals
                if stored.decision.outcome == "accepted"
                and stored.proposal.goal.canonical_hash == objective.objective.goal.canonical_hash
                and stored.proposal.proposal_id in budget.reservations
            ]
            if len(proposal_reservations) != 1:
                raise ValueError("child objective budget reservation is ambiguous")
            reservation_id = proposal_reservations[0]
        await self._repository.save_budget(
            transition.mission_id,
            budget.settle(reservation_id, transition.actual_budget),
            updated_at_ms=transition.occurred_at_ms,
        )

        if transition.verification == "verified" and command.state in {
            CommandState.SUCCEEDED,
            CommandState.SUCCEEDED_RECONCILED,
        }:
            target = ObjectiveStatus.COMPLETED
            reason = "CHILD_VERIFIED_COMPLETE"
        elif transition.verification == "unknown" or command.state is CommandState.BLOCKED_UNKNOWN:
            target = ObjectiveStatus.BLOCKED_UNKNOWN
            reason = "CHILD_OUTCOME_UNKNOWN"
        else:
            target = ObjectiveStatus.FAILED
            reason = "CHILD_VERIFICATION_FAILED"
        await self._repository.transition_objective(
            transition.mission_id,
            transition.objective_id,
            expected_version=objective.version,
            target=target,
            reason_code=reason,
            actor="mission-coordinator",
            occurred_at_ms=transition.occurred_at_ms,
            details={"command_id": transition.command_id},
            evidence_refs=transition.evidence_refs,
        )
        for ordinal, evidence_ref in enumerate(transition.evidence_refs):
            link_hash = canonical_json_hash(
                {
                    "mission_id": transition.mission_id,
                    "objective_id": transition.objective_id,
                    "command_id": transition.command_id,
                    "evidence_ref": evidence_ref,
                }
            )
            await self._repository.link_evidence(
                MissionEvidenceLink(
                    link_id=f"evidence-{link_hash[:24]}-{ordinal}",
                    mission_id=transition.mission_id,
                    objective_id=transition.objective_id,
                    evidence_kind=evidence_ref.partition(":")[0],
                    evidence_ref=evidence_ref,
                    command_id=transition.command_id,
                    attributable=True,
                    linked_at_ms=transition.occurred_at_ms,
                )
            )
        if target is ObjectiveStatus.BLOCKED_UNKNOWN:
            mission = await self._repository.transition_mission(
                transition.mission_id,
                expected_version=snapshot.mission.version,
                target=MissionStatus.BLOCKED_UNKNOWN,
                reason_code="CHILD_OUTCOME_UNKNOWN",
                actor="mission-coordinator",
                occurred_at_ms=transition.occurred_at_ms,
                evidence_refs=transition.evidence_refs,
            )
            return MissionAdvanceResult(
                mission_id=transition.mission_id,
                mission_status=mission.status,
            )
        if target is ObjectiveStatus.FAILED:
            mission = await self._repository.transition_mission(
                transition.mission_id,
                expected_version=snapshot.mission.version,
                target=MissionStatus.FAILED,
                reason_code="REQUIRED_CHILD_FAILED",
                actor="mission-coordinator",
                occurred_at_ms=transition.occurred_at_ms,
                evidence_refs=transition.evidence_refs,
            )
            return MissionAdvanceResult(
                mission_id=transition.mission_id,
                mission_status=mission.status,
            )
        return await self._advance(
            transition.mission_id,
            caller_scope=snapshot.mission.caller_scope,
            occurred_at_ms=transition.occurred_at_ms,
        )
