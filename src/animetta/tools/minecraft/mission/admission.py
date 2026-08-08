"""Pure deterministic admission for mission child-goal proposals."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from animetta.tools.gamebot.contracts.v2 import RuntimeManifest
from animetta.tools.minecraft.voyager.budget import (
    BudgetAccount,
    BudgetExceededError,
    BudgetUsage,
)

from .models import GoalAdmissionDecision, GoalProposal, MissionSpec

GoalDomain = Literal["gameplay", "discovery", "skill", "technology", "recovery"]

_GOAL_DOMAIN: dict[str, GoalDomain] = {
    "acquire": "gameplay",
    "craft": "gameplay",
    "build": "gameplay",
    "travel": "gameplay",
    "combat": "gameplay",
    "survive": "gameplay",
    "learn": "skill",
    "discover": "discovery",
}
_REQUIRED_CAPABILITY = {
    "acquire": "collect",
    "craft": "craft",
    "build": "place",
    "travel": "goto",
    "combat": "attack",
    "survive": "observe",
    "learn": "observe",
    "discover": "observe",
}
_RISK_RANK = {"read_only": 0, "survival_safe": 1, "destructive": 2}
_AUTONOMY_DOMAIN_BY_RATIONALE: dict[str, GoalDomain] = {
    "DISCOVERY_GAP": "discovery",
    "UNVISITED_FRONTIER": "discovery",
    "SKILL_GAP": "skill",
    "TECHNOLOGY_FRONTIER": "technology",
    "RECOVERY_PREREQUISITE": "recovery",
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AdmissionContext(_FrozenModel):
    """All durable facts consulted by one pure admission decision."""

    mission: MissionSpec
    manifest: RuntimeManifest
    budget_account: BudgetAccount
    completed_objective_ids: frozenset[str] = frozenset()
    seen_proposal_ids: frozenset[str] = frozenset()
    admitted_goal_hashes: frozenset[str] = frozenset()
    admitted_child_count: int = 0
    runtime_quarantined: bool = False


class AdmissionResult(_FrozenModel):
    decision: GoalAdmissionDecision
    context: AdmissionContext


class GoalAdmission:
    """Admit proposals without executing capabilities or mutating shared state."""

    @staticmethod
    def _decision(
        proposal: GoalProposal,
        context: AdmissionContext,
        outcome: Literal["accepted", "rejected", "deferred"],
        reason_code: str,
        *,
        reserved_budget: BudgetUsage | None = None,
    ) -> AdmissionResult:
        decision = GoalAdmissionDecision.model_validate(
            {
                "proposal_id": proposal.proposal_id,
                "outcome": outcome,
                "reason_code": reason_code,
                "reserved_budget": reserved_budget,
            }
        )
        if outcome == "deferred":
            return AdmissionResult(decision=decision, context=context)
        return AdmissionResult(
            decision=decision,
            context=context.model_copy(
                update={
                    "seen_proposal_ids": context.seen_proposal_ids
                    | frozenset({proposal.proposal_id})
                }
            ),
        )

    def admit(self, proposal: GoalProposal, context: AdmissionContext) -> AdmissionResult:
        """Return one closed admission decision and updated immutable budget context."""

        if proposal.mission_id != context.mission.mission_id:
            return self._decision(proposal, context, "rejected", "INVALID_SCHEMA")
        if (
            proposal.proposal_id in context.seen_proposal_ids
            or proposal.goal.canonical_hash in context.admitted_goal_hashes
        ):
            return self._decision(proposal, context, "rejected", "DUPLICATE_PROPOSAL")
        if context.runtime_quarantined:
            return self._decision(proposal, context, "deferred", "RUNTIME_QUARANTINED")
        if (
            proposal.parent_objective_id is not None
            and proposal.parent_objective_id not in context.completed_objective_ids
        ):
            return self._decision(proposal, context, "deferred", "DEPENDENCY_UNSATISFIED")

        domain = _GOAL_DOMAIN[proposal.goal.intent]
        if domain not in context.mission.allowed_domains:
            return self._decision(proposal, context, "rejected", "DOMAIN_FORBIDDEN")
        if proposal.origin in {"curriculum", "recovery"}:
            if context.mission.autonomy.mode != "bounded":
                return self._decision(proposal, context, "rejected", "SOURCE_FORBIDDEN")
            if context.admitted_child_count >= context.mission.autonomy.max_child_goals:
                return self._decision(
                    proposal,
                    context,
                    "rejected",
                    "CHILD_GOAL_LIMIT_REACHED",
                )
            required_domain: GoalDomain = (
                "recovery"
                if proposal.origin == "recovery"
                else _AUTONOMY_DOMAIN_BY_RATIONALE.get(
                    proposal.rationale_code,
                    domain,
                )
            )
            if required_domain not in context.mission.autonomy.allowed_domains:
                return self._decision(proposal, context, "rejected", "SOURCE_FORBIDDEN")

        capability_name = _REQUIRED_CAPABILITY[proposal.goal.intent]
        capabilities = {capability.name: capability for capability in context.manifest.capabilities}
        capability = capabilities.get(capability_name)
        if capability is None:
            return self._decision(
                proposal,
                context,
                "rejected",
                "MANIFEST_CAPABILITY_MISSING",
            )
        if (
            proposal.origin in {"curriculum", "recovery"}
            and _RISK_RANK[str(capability.risk)] > _RISK_RANK[context.mission.autonomy.max_risk]
        ):
            return self._decision(proposal, context, "rejected", "RISK_FORBIDDEN")

        try:
            budget = context.budget_account.reserve(
                proposal.proposal_id, proposal.conservative_cost
            )
        except BudgetExceededError:
            return self._decision(proposal, context, "rejected", "BUDGET_EXHAUSTED")
        updated = context.model_copy(
            update={
                "budget_account": budget,
                "seen_proposal_ids": context.seen_proposal_ids | frozenset({proposal.proposal_id}),
                "admitted_goal_hashes": context.admitted_goal_hashes
                | frozenset({proposal.goal.canonical_hash}),
                "admitted_child_count": context.admitted_child_count + 1,
            }
        )
        return AdmissionResult(
            decision=GoalAdmissionDecision(
                proposal_id=proposal.proposal_id,
                outcome="accepted",
                reason_code="ADMITTED",
                reserved_budget=proposal.conservative_cost,
            ),
            context=updated,
        )

    def settle(
        self,
        context: AdmissionContext,
        proposal_id: str,
        actual: BudgetUsage,
    ) -> AdmissionContext:
        """Charge attributable actual usage and release unused reservation."""

        return context.model_copy(
            update={"budget_account": context.budget_account.settle(proposal_id, actual)}
        )
