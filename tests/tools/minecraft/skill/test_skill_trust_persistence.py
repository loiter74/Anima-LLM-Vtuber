"""Candidate/trusted skill stages and provenance survive SQLite migration."""

from __future__ import annotations

import sqlite3

from animetta.tools.minecraft.skill import models as skill_models
from animetta.tools.minecraft.skill.catalog import SkillLibrary


def _provenance(*, validated: bool = False):
    return skill_models.SkillProvenance(
        source_session_id="learn-session-1",
        source_task_id="task-wood",
        policy_report={"allowed": True, "violations": []},
        evidence_refs=["receipt-hash-1"],
        validation_session_id="validation-session-1" if validated else "",
        environment_fingerprint="seed:123|runtime:runtime-1",
    )


async def test_candidate_skill_and_provenance_survive_restart(tmp_path) -> None:
    db_path = str(tmp_path / "candidate.db")
    skill = skill_models.Skill(
        id="candidate-wood",
        name="Collect wood",
        description="candidate",
        is_learned=True,
        trust_stage=skill_models.SkillTrustStage.CANDIDATE,
        provenance=_provenance(),
    )
    lib = SkillLibrary(db_path=db_path)
    await lib.init_db()
    await lib.save_skill(skill)
    await lib.close_db()

    reloaded = SkillLibrary(db_path=db_path)
    await reloaded.init_db()
    loaded = await reloaded.get_skill(skill.id)

    assert loaded.trust_stage is skill_models.SkillTrustStage.CANDIDATE
    assert loaded.is_trusted is False
    assert loaded.provenance.source_session_id == "learn-session-1"
    assert loaded.provenance.evidence_refs == ["receipt-hash-1"]
    await reloaded.close_db()


async def test_trusted_skill_requires_and_preserves_validation_provenance(tmp_path) -> None:
    db_path = str(tmp_path / "trusted.db")
    skill = skill_models.Skill(
        id="trusted-wood",
        name="Collect wood",
        description="trusted",
        is_learned=True,
        trust_stage=skill_models.SkillTrustStage.TRUSTED,
        provenance=_provenance(validated=True),
    )
    lib = SkillLibrary(db_path=db_path)
    await lib.init_db()
    await lib.save_skill(skill)
    await lib.close_db()

    reloaded = SkillLibrary(db_path=db_path)
    await reloaded.init_db()
    loaded = await reloaded.get_skill(skill.id)

    assert loaded.is_trusted is True
    assert loaded.provenance.validation_session_id == "validation-session-1"
    assert loaded.provenance.environment_fingerprint.startswith("seed:123")
    await reloaded.close_db()


async def test_legacy_validated_row_migrates_to_candidate_without_provenance(tmp_path) -> None:
    db_path = str(tmp_path / "legacy.db")
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE skills (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '',
                parameters_json TEXT DEFAULT '{}', preconditions_json TEXT DEFAULT '[]',
                body_json TEXT DEFAULT '{}', steps_json TEXT DEFAULT '[]', category TEXT DEFAULT '',
                postconditions_json TEXT DEFAULT '[]', success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0, avg_duration REAL DEFAULT 0.0,
                last_used TEXT DEFAULT '', tags_json TEXT DEFAULT '[]', is_learned INTEGER DEFAULT 0,
                validated INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            "INSERT INTO skills (id, name, is_learned, validated) VALUES (?, ?, ?, ?)",
            ("legacy-verified", "Legacy Verified", 1, 1),
        )
        db.commit()

    lib = SkillLibrary(db_path=db_path)
    await lib.init_db()
    loaded = await lib.get_skill("legacy-verified")

    assert loaded.validated is True
    assert loaded.trust_stage is skill_models.SkillTrustStage.CANDIDATE
    assert loaded.is_trusted is False
    assert loaded.provenance.validation_session_id == ""
    await lib.close_db()


async def test_demotion_persists_reason_without_deleting_validation_history(tmp_path) -> None:
    db_path = str(tmp_path / "demotion.db")
    skill = skill_models.Skill(
        id="flaky-trusted",
        name="Collect wood",
        description="trusted then flaky",
        is_learned=True,
        trust_stage=skill_models.SkillTrustStage.TRUSTED,
        provenance=_provenance(validated=True),
    )
    lib = SkillLibrary(db_path=db_path)
    await lib.init_db()
    await lib.save_skill(skill)

    await lib.demote_skill(
        skill.id,
        reason="three consecutive live failures",
        session_id="live-session-2",
    )
    await lib.close_db()

    reloaded = SkillLibrary(db_path=db_path)
    await reloaded.init_db()
    loaded = await reloaded.get_skill(skill.id)

    assert loaded.trust_stage is skill_models.SkillTrustStage.CANDIDATE
    assert loaded.is_trusted is False
    assert loaded.provenance.validation_session_id == "validation-session-1"
    assert loaded.provenance.history[-1] == {
        "event": "demoted",
        "reason": "three consecutive live failures",
        "session_id": "live-session-2",
    }
    await reloaded.close_db()
