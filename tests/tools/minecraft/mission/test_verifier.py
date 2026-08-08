from __future__ import annotations

from animetta.tools.minecraft.mission.models import (
    MissionSpec,
    NovelFactsAcquiredAtLeast,
    TrustedSkillsCreatedAtLeast,
    VanillaAdvancementsAddedAtLeast,
)
from animetta.tools.minecraft.mission.verifier import (
    MissionEvidenceSnapshot,
    MissionVerifier,
)
from tests.tools.minecraft.mission.test_models import _mission_payload


def test_mission_verifier_keeps_vanilla_and_internal_technology_separate() -> None:
    base = MissionSpec.model_validate(_mission_payload())
    spec = MissionSpec.model_validate(
        {
            **base.model_dump(mode="json"),
            "completion_predicates": [
                NovelFactsAcquiredAtLeast(kind="novel_facts_acquired_at_least", count=1),
                TrustedSkillsCreatedAtLeast(kind="trusted_skills_created_at_least", count=1),
                VanillaAdvancementsAddedAtLeast(
                    kind="vanilla_advancements_added_at_least",
                    count=2,
                ),
            ],
        }
    )
    evidence = MissionEvidenceSnapshot(
        acquired_world_fact_ids=frozenset({"fact-1"}),
        trusted_skill_revision_hashes=frozenset({"a" * 64}),
        vanilla_advancement_ids=frozenset({"minecraft:story/root"}),
        technology_evidence_ids=frozenset({"tech-root", "tech-stone"}),
    )

    result = MissionVerifier().verify(
        spec=spec,
        objective_results={objective.objective_id: True for objective in spec.objectives},
        evidence=evidence,
    )

    assert result.satisfied is False
    assert result.completion_predicates["vanilla_advancements_added_at_least"] is False
    assert result.technology_evidence_count == 2
