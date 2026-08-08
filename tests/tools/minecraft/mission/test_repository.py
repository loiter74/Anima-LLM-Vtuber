from __future__ import annotations

import sqlite3
from importlib import import_module
from pathlib import Path

import pytest

from animetta.tools.minecraft.mission.models import (
    GoalAdmissionDecision,
    MissionObjective,
    MissionSpec,
)
from animetta.tools.minecraft.voyager.budget import BudgetAccount

from .test_admission import _proposal
from .test_models import _mission_payload


def _repository_module():
    return import_module("animetta.tools.minecraft.mission.repository")


def _mission() -> MissionSpec:
    return MissionSpec.model_validate(_mission_payload())


async def _exercise_repository(repository, module) -> None:
    await repository.connect()
    mission = _mission()
    created, reused = await repository.create_mission(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1_000,
    )
    duplicate, duplicate_reused = await repository.create_mission(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1_001,
    )

    assert reused is False
    assert duplicate_reused is True
    assert duplicate == created
    assert created.status == "accepted"
    objectives = await repository.list_objectives(mission.mission_id)
    assert [record.objective.objective_id for record in objectives] == [
        "fight-zombie",
        "discover-copper",
    ]
    assert all(record.status == "pending" for record in objectives)

    transition = await repository.append_transition(
        module.MissionTransitionDraft(
            mission_id=mission.mission_id,
            objective_id="fight-zombie",
            entity_version=1,
            from_state="pending",
            to_state="active",
            reason_code="DEPENDENCIES_SATISFIED",
            actor="mission-coordinator",
            details={"source": "initial-dag"},
            evidence_refs=("mission:showcase-001",),
            occurred_at_ms=1_100,
        )
    )
    proposal = _proposal()
    decision = GoalAdmissionDecision(
        proposal_id=proposal.proposal_id,
        outcome="accepted",
        reason_code="ADMITTED",
        reserved_budget=proposal.conservative_cost,
    )
    await repository.save_proposal(proposal, decision, occurred_at_ms=1_200)
    dynamic_objective = await repository.append_objective(
        mission.mission_id,
        MissionObjective(
            objective_id="child-discover-copper",
            goal=proposal.goal,
            dependencies=("discover-copper",),
            required=True,
            priority=40,
            budget=proposal.conservative_cost,
        ),
        reason_code="AUTONOMOUS_PROPOSAL_ADMITTED",
        actor="mission-coordinator",
        occurred_at_ms=1_200,
        evidence_refs=proposal.evidence_refs,
    )
    account = BudgetAccount(limit=mission.budget).reserve(
        proposal.proposal_id, proposal.conservative_cost
    )
    await repository.save_budget(mission.mission_id, account, updated_at_ms=1_201)
    await repository.link_evidence(
        module.MissionEvidenceLink(
            link_id="evidence-link-001",
            mission_id=mission.mission_id,
            objective_id="fight-zombie",
            evidence_kind="receipt",
            evidence_ref="receipt:receipt-001",
            command_id="command-001",
            attributable=True,
            linked_at_ms=1_300,
        )
    )
    await repository.save_presentation_artifact(
        module.PresentationArtifact(
            artifact_id="artifact-001",
            mission_id=mission.mission_id,
            stage_id="combat-zombie",
            artifact_kind="screenshot",
            path="evidence/minecraft-adaptive-showcase/combat-zombie.png",
            sha256="a" * 64,
            captured_at_ms=1_400,
            sanitized=True,
        )
    )

    snapshot = await repository.snapshot(mission.mission_id)
    assert snapshot.mission == created
    assert snapshot.transitions[0] == transition
    assert snapshot.transitions[-1].reason_code == "AUTONOMOUS_PROPOSAL_ADMITTED"
    assert snapshot.transitions[-1].objective_id == dynamic_objective.objective.objective_id
    assert snapshot.proposals[0].proposal == proposal
    assert snapshot.proposals[0].decision == decision
    assert snapshot.objectives[-1] == dynamic_objective
    assert snapshot.mission.spec.objectives == mission.objectives
    assert snapshot.budget == account
    assert snapshot.evidence_links[0].evidence_ref == "receipt:receipt-001"
    assert snapshot.presentation_artifacts[0].sha256 == "a" * 64
    await repository.close()


async def test_in_memory_and_sqlite_repositories_round_trip_all_additive_records(
    tmp_path: Path,
) -> None:
    module = _repository_module()

    await _exercise_repository(module.InMemoryMissionRepository(), module)
    await _exercise_repository(
        module.SQLiteMissionRepository(tmp_path / "minecraft-journal.db"), module
    )


async def test_repository_rejects_idempotency_key_reuse_with_a_different_spec(
    tmp_path: Path,
) -> None:
    module = _repository_module()
    repository = module.SQLiteMissionRepository(tmp_path / "idempotency.db")
    await repository.connect()
    mission = _mission()
    await repository.create_mission(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1,
    )
    changed_payload = _mission_payload()
    changed_payload["mission_id"] = "showcase-002"

    with pytest.raises(module.MissionIdempotencyConflictError, match="IDEMPOTENCY_CONFLICT"):
        await repository.create_mission(
            caller_scope="conversation:user-001",
            request_id="request-001",
            spec=MissionSpec.model_validate(changed_payload),
            occurred_at_ms=2,
        )
    await repository.close()


async def test_sqlite_migration_is_additive_and_preserves_legacy_history(
    tmp_path: Path,
) -> None:
    module = _repository_module()
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE commands (command_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE skills (skill_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT INTO commands VALUES ('legacy-command', 'unchanged')")
        db.execute("INSERT INTO skills VALUES ('legacy-skill', 'unchanged')")
        before = {
            name: db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()[0]
            for name in ("commands", "skills")
        }

    repository = module.SQLiteMissionRepository(path)
    await repository.connect()
    await repository.close()

    with sqlite3.connect(path) as db:
        after = {
            name: db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()[0]
            for name in ("commands", "skills")
        }
        assert after == before
        assert db.execute("SELECT * FROM commands").fetchall() == [("legacy-command", "unchanged")]
        assert db.execute("SELECT * FROM skills").fetchall() == [("legacy-skill", "unchanged")]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "missions",
            "mission_objectives",
            "mission_transitions",
            "goal_proposals",
            "mission_budgets",
            "mission_evidence_links",
            "presentation_artifacts",
        }.issubset(tables)
