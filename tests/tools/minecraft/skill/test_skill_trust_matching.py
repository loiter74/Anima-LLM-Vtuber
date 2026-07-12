"""Trusted-only skill queries used by live execution."""

from __future__ import annotations

from animetta.tools.minecraft.skill.catalog import SkillLibrary
from animetta.tools.minecraft.skill.models import (
    Skill,
    SkillProvenance,
    SkillTrustStage,
)


def _skill(skill_id: str, stage: SkillTrustStage, *, validated: bool = True) -> Skill:
    provenance = SkillProvenance(
        source_session_id="learn-session",
        source_task_id=skill_id,
        evidence_refs=[f"receipt-{skill_id}"],
        validation_session_id="validation-session" if stage is SkillTrustStage.TRUSTED else "",
        environment_fingerprint="test",
    )
    return Skill(
        id=skill_id,
        name="collect wood",
        description=skill_id,
        validated=validated,
        trust_stage=stage,
        provenance=provenance,
        success_count=5,
    )


async def test_match_trusted_skills_excludes_candidates_even_when_validated_true() -> None:
    library = SkillLibrary()
    await library.save_skill(_skill("candidate", SkillTrustStage.CANDIDATE))
    await library.save_skill(_skill("trusted", SkillTrustStage.TRUSTED))

    matches = await library.match_trusted_skills({})

    assert [skill.id for skill in matches] == ["trusted"]


async def test_match_trusted_skills_preserves_preconditions_and_ranking() -> None:
    library = SkillLibrary()
    slow = _skill("slow", SkillTrustStage.TRUSTED)
    slow.avg_duration = 30
    slow.preconditions = ["is_day"]
    fast = _skill("fast", SkillTrustStage.TRUSTED)
    fast.avg_duration = 5
    fast.preconditions = ["is_day"]
    blocked = _skill("blocked", SkillTrustStage.TRUSTED)
    blocked.preconditions = ["is_night"]
    for skill in (slow, fast, blocked):
        await library.save_skill(skill)

    matches = await library.match_trusted_skills({"is_day": True, "is_night": False})

    assert [skill.id for skill in matches] == ["fast", "slow"]


async def test_success_resets_consecutive_failures_and_failure_increments_it() -> None:
    library = SkillLibrary()
    skill = _skill("flaky", SkillTrustStage.TRUSTED)
    skill.consecutive_failures = 2
    await library.save_skill(skill)

    await library.update_success(skill.id)
    assert (await library.get_skill(skill.id)).consecutive_failures == 0

    await library.update_failure(skill.id)
    assert (await library.get_skill(skill.id)).consecutive_failures == 1
