"""Independent mission completion verification across separated evidence domains."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from animetta.tools.gamebot.contracts.v2 import canonical_json_hash

from .models import (
    MissionSpec,
    NovelFactsAcquiredAtLeast,
    TrustedSkillsCreatedAtLeast,
    VanillaAdvancementsAddedAtLeast,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MissionEvidenceSnapshot(_FrozenModel):
    acquired_world_fact_ids: frozenset[str] = frozenset()
    trusted_skill_revision_hashes: frozenset[str] = frozenset()
    vanilla_advancement_ids: frozenset[str] = frozenset()
    technology_evidence_ids: frozenset[str] = frozenset()


class MissionVerificationResult(_FrozenModel):
    satisfied: bool
    objective_results: dict[str, bool]
    completion_predicates: dict[str, bool]
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    technology_evidence_count: int = Field(ge=0)


class MissionVerifier:
    def verify(
        self,
        *,
        spec: MissionSpec,
        objective_results: dict[str, bool],
        evidence: MissionEvidenceSnapshot,
    ) -> MissionVerificationResult:
        normalized_objectives = {
            objective.objective_id: bool(objective_results.get(objective.objective_id, False))
            for objective in spec.objectives
        }
        required_satisfied = all(
            normalized_objectives[objective.objective_id]
            for objective in spec.objectives
            if objective.required
        )
        predicate_results: dict[str, bool] = {}
        for predicate in spec.completion_predicates:
            if isinstance(predicate, NovelFactsAcquiredAtLeast):
                satisfied = len(evidence.acquired_world_fact_ids) >= predicate.count
            elif isinstance(predicate, TrustedSkillsCreatedAtLeast):
                satisfied = len(evidence.trusted_skill_revision_hashes) >= predicate.count
            elif isinstance(predicate, VanillaAdvancementsAddedAtLeast):
                satisfied = len(evidence.vanilla_advancement_ids) >= predicate.count
            else:  # pragma: no cover - closed typed union
                satisfied = False
            predicate_results[predicate.kind] = satisfied

        evidence_payload = {
            "mission_hash": spec.canonical_hash,
            "objectives": dict(sorted(normalized_objectives.items())),
            "completion_predicates": dict(sorted(predicate_results.items())),
            "acquired_world_fact_ids": sorted(evidence.acquired_world_fact_ids),
            "trusted_skill_revision_hashes": sorted(evidence.trusted_skill_revision_hashes),
            "vanilla_advancement_ids": sorted(evidence.vanilla_advancement_ids),
            "technology_evidence_ids": sorted(evidence.technology_evidence_ids),
        }
        return MissionVerificationResult(
            satisfied=required_satisfied and all(predicate_results.values()),
            objective_results=normalized_objectives,
            completion_predicates=predicate_results,
            evidence_hash=canonical_json_hash(evidence_payload),
            technology_evidence_count=len(evidence.technology_evidence_ids),
        )
