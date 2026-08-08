from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath

from animetta.tools.minecraft.mission.coordinator import (
    MissionCoordinator,
    VerifiedChildTransition,
)
from animetta.tools.minecraft.mission.repository import InMemoryMissionRepository
from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.journal import InMemoryCommandJournal
from tooling.quality.minecraft_architecture import audit_source

from .test_coordinator import _fixed_mission


async def test_concurrent_idempotent_submissions_create_exactly_one_child() -> None:
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    coordinator = MissionCoordinator(repository=repository, journal=journal)
    mission = _fixed_mission()

    results = await asyncio.gather(
        *(
            coordinator.submit(
                caller_scope="conversation:user-001",
                request_id="request-001",
                spec=mission,
                occurred_at_ms=1_000 + index,
            )
            for index in range(12)
        )
    )

    commands = (await journal.read_projection("conversation:user-001")).commands
    assert len(commands) == 1
    assert commands[0].state is CommandState.QUEUED
    assert {result.eligible_command_id for result in results} == {commands[0].command_id}


async def test_stop_barrier_cancels_mission_and_prevents_more_children() -> None:
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    coordinator = MissionCoordinator(repository=repository, journal=journal)
    mission = _fixed_mission()
    submitted = await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1_000,
    )

    stopped = await coordinator.stop(
        mission.mission_id,
        request_id="stop-001",
        reason="user requested stop",
        occurred_at_ms=1_100,
    )
    after = await coordinator.advance_from_committed_evidence(
        mission.mission_id, occurred_at_ms=1_200
    )

    assert stopped.mission_status == "cancelled"
    assert after.eligible_command_id is None
    snapshot = await repository.snapshot(mission.mission_id)
    assert snapshot.mission.status == "cancelled"
    assert snapshot.objectives[0].status == "cancelled"
    command = await journal.get_command(submitted.eligible_command_id)
    assert command is not None
    assert command.state is CommandState.CANCELLED_BY_STOP


async def test_restart_blocks_running_child_without_replay() -> None:
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    first = MissionCoordinator(repository=repository, journal=journal)
    mission = _fixed_mission()
    submitted = await first.submit(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1_000,
    )
    queued = await journal.get_command(submitted.eligible_command_id)
    assert queued is not None
    await journal.transition(
        queued.command_id,
        expected_version=queued.state_version,
        target=CommandState.RUNNING,
        reason_code="WORKER_CLAIMED",
        actor="worker",
        occurred_at_ms=1_010,
    )

    restarted = MissionCoordinator(repository=repository, journal=journal)
    recovered = await restarted.recover_startup(mission.mission_id, occurred_at_ms=2_000)

    assert recovered.mission_status == "blocked_unknown"
    assert recovered.eligible_command_id is None
    assert len((await journal.read_projection("conversation:user-001")).commands) == 1
    snapshot = await repository.snapshot(mission.mission_id)
    assert snapshot.objectives[0].status == "blocked_unknown"


async def test_unknown_child_transition_quarantines_mission_without_next_child() -> None:
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    coordinator = MissionCoordinator(repository=repository, journal=journal)
    mission = _fixed_mission()
    submitted = await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-001",
        spec=mission,
        occurred_at_ms=1_000,
    )
    queued = await journal.get_command(submitted.eligible_command_id)
    assert queued is not None
    running = await journal.transition(
        queued.command_id,
        expected_version=queued.state_version,
        target=CommandState.RUNNING,
        reason_code="WORKER_CLAIMED",
        actor="worker",
        occurred_at_ms=1_010,
    )
    await journal.transition(
        running.command_id,
        expected_version=running.state_version,
        target=CommandState.BLOCKED_UNKNOWN,
        reason_code="RUNTIME_DISCONNECTED",
        actor="controller",
        occurred_at_ms=1_011,
    )

    result = await coordinator.on_child_transition(
        VerifiedChildTransition(
            mission_id=mission.mission_id,
            objective_id="fight-zombie",
            command_id=running.command_id,
            command_state="blocked_unknown",
            verification="unknown",
            evidence_refs=("recovery:unknown-001",),
            occurred_at_ms=1_012,
        )
    )

    assert result.mission_status == "blocked_unknown"
    assert result.eligible_command_id is None
    assert len((await journal.read_projection("conversation:user-001")).commands) == 1


def test_architecture_audit_confirms_coordinator_has_no_gameplay_call() -> None:
    source = PurePosixPath("src/animetta/tools/minecraft/mission/coordinator.py").as_posix()
    disk = Path(__file__).resolve().parents[4] / source
    codes = {
        violation.code
        for violation in audit_source(PurePosixPath(source), disk.read_text(encoding="utf-8"))
    }

    assert "DIRECT_GAMEPLAY_CALL" not in codes
