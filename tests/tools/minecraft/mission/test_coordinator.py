from __future__ import annotations

from importlib import import_module

from animetta.tools.minecraft.mission.models import MissionSpec
from animetta.tools.minecraft.mission.repository import InMemoryMissionRepository
from animetta.tools.minecraft.mission.verifier import MissionEvidenceSnapshot
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.journal import InMemoryCommandJournal

from .test_models import _mission_payload


def _coordinator_module():
    return import_module("animetta.tools.minecraft.mission.coordinator")


def _fixed_mission() -> MissionSpec:
    payload = _mission_payload()
    payload["completion_predicates"] = []
    payload["autonomy"] = {"mode": "off"}
    payload["execution"] = {
        "reuse_trusted_skill": True,
        "allow_skill_learning": False,
        "allow_deterministic_fallback": False,
    }
    return MissionSpec.model_validate(payload)


async def _complete_command(journal: InMemoryCommandJournal, command_id: str, now: int) -> None:
    queued = await journal.get_command(command_id)
    assert queued is not None
    running = await journal.transition(
        command_id,
        expected_version=queued.state_version,
        target=CommandState.RUNNING,
        reason_code="WORKER_CLAIMED",
        actor="worker",
        occurred_at_ms=now,
    )
    await journal.transition(
        command_id,
        expected_version=running.state_version,
        target=CommandState.SUCCEEDED,
        reason_code="VERIFIED_SUCCESS",
        actor="controller",
        occurred_at_ms=now + 1,
    )


async def test_transition_driven_coordinator_queues_at_most_one_ready_leaf() -> None:
    module = _coordinator_module()
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    await repository.connect()
    coordinator = module.MissionCoordinator(repository=repository, journal=journal)
    mission = _fixed_mission()

    submitted = await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1_000,
    )

    assert submitted.eligible_objective_id == "fight-zombie"
    assert submitted.eligible_command_id is not None
    first_page = await journal.read_projection("conversation:user-001")
    assert len(first_page.commands) == 1
    first_snapshot = await repository.snapshot(mission.mission_id)
    assert first_snapshot.mission.status == "running"
    assert [item.status for item in first_snapshot.objectives] == ["active", "pending"]

    await _complete_command(journal, submitted.eligible_command_id, 1_100)
    advanced = await coordinator.on_child_transition(
        module.VerifiedChildTransition(
            mission_id=mission.mission_id,
            objective_id="fight-zombie",
            command_id=submitted.eligible_command_id,
            command_state="succeeded",
            verification="verified",
            evidence_refs=("receipt:combat-001",),
            actual_budget=BudgetUsage(max_actions=1, max_strategy_attempts=1),
            occurred_at_ms=1_102,
        )
    )

    assert advanced.eligible_objective_id == "discover-copper"
    assert advanced.eligible_command_id is not None
    second_page = await journal.read_projection("conversation:user-001")
    assert len(second_page.commands) == 2
    second_snapshot = await repository.snapshot(mission.mission_id)
    assert [item.status for item in second_snapshot.objectives] == ["completed", "active"]
    assert second_snapshot.budget is not None
    assert second_snapshot.budget.used == BudgetUsage(
        max_actions=1,
        max_strategy_attempts=1,
    )
    assert "objective:fight-zombie" not in second_snapshot.budget.reservations
    assert second_snapshot.budget.remaining.max_actions == 15

    await _complete_command(journal, advanced.eligible_command_id, 1_200)
    finished = await coordinator.on_child_transition(
        module.VerifiedChildTransition(
            mission_id=mission.mission_id,
            objective_id="discover-copper",
            command_id=advanced.eligible_command_id,
            command_state="succeeded",
            verification="verified",
            evidence_refs=("observation:discovery-001",),
            occurred_at_ms=1_202,
        )
    )

    assert finished.eligible_command_id is None
    assert (await repository.snapshot(mission.mission_id)).mission.status == "completed"
    final_page = await journal.read_projection("conversation:user-001")
    assert len(final_page.commands) == 2


async def test_idempotent_submission_does_not_queue_a_second_child() -> None:
    module = _coordinator_module()
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    coordinator = module.MissionCoordinator(repository=repository, journal=journal)
    mission = _fixed_mission()

    first = await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1,
    )
    reused = await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=2,
    )

    assert reused.idempotency_reused is True
    assert reused.eligible_command_id == first.eligible_command_id
    assert len((await journal.read_projection("conversation:user-001")).commands) == 1


def test_coordinator_has_no_runtime_or_bridge_execution_dependency() -> None:
    module = _coordinator_module()

    assert not {"runtime", "bridge", "controller", "executor"}.intersection(
        module.MissionCoordinator.__annotations__
    )


async def test_waiting_evidence_completes_only_after_independent_mission_verification() -> None:
    module = _coordinator_module()
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    coordinator = module.MissionCoordinator(repository=repository, journal=journal)
    mission = MissionSpec.model_validate(_mission_payload())
    current = await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-evidence",
        spec=mission,
        occurred_at_ms=1_000,
    )
    now = 1_100
    for objective in mission.objectives:
        assert current.eligible_command_id is not None
        await _complete_command(journal, current.eligible_command_id, now)
        current = await coordinator.on_child_transition(
            module.VerifiedChildTransition(
                mission_id=mission.mission_id,
                objective_id=objective.objective_id,
                command_id=current.eligible_command_id,
                command_state="succeeded",
                verification="verified",
                evidence_refs=(f"receipt:{objective.objective_id}",),
                occurred_at_ms=now + 2,
            )
        )
        now += 100

    assert current.mission_status == "waiting_evidence"
    still_waiting = await coordinator.verify_completion(
        mission.mission_id,
        evidence=MissionEvidenceSnapshot(),
        occurred_at_ms=now,
    )
    completed = await coordinator.verify_completion(
        mission.mission_id,
        evidence=MissionEvidenceSnapshot(
            acquired_world_fact_ids=frozenset({"fact-1"}),
            trusted_skill_revision_hashes=frozenset({"a" * 64}),
            vanilla_advancement_ids=frozenset(
                {"minecraft:story/root", "minecraft:story/mine_stone"}
            ),
        ),
        occurred_at_ms=now + 1,
    )

    assert still_waiting.mission_status == "waiting_evidence"
    assert completed.mission_status == "completed"
    assert completed.completion_evidence_hash is not None
