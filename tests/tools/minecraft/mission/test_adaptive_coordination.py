from __future__ import annotations

from animetta.tools.minecraft.discovery.exploration import (
    ExplorationBounds,
    ExplorationInput,
    ExplorationProposer,
    ExplorationSeed,
)
from animetta.tools.minecraft.mission.models import MissionSpec
from animetta.tools.minecraft.mission.repository import InMemoryMissionRepository
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.goal_models import (
    DiscoverGoal,
    WorldFactObserved,
)
from animetta.tools.minecraft.voyager.journal import InMemoryCommandJournal

from .test_admission import _manifest
from .test_coordinator import _coordinator_module, _fixed_mission
from .test_models import _mission_payload


def _exploration_input() -> ExplorationInput:
    return ExplorationInput(
        mission_id="showcase-001",
        observation_ref="observation:obs-adaptive-001",
        observation_committed=True,
        new_facts=(
            ExplorationSeed(
                source="new_fact",
                signal_id="signal-copper-frontier",
                goal=DiscoverGoal(
                    intent="discover",
                    target="minecraft:raw_copper",
                    discovery_kind="item",
                    success_predicates=(
                        WorldFactObserved(
                            kind="world_fact_observed",
                            fact_kind="item",
                            fact_key="minecraft:raw_copper",
                        ),
                    ),
                ),
                evidence_refs=("world-fact:copper-001",),
                conservative_cost=BudgetUsage(max_actions=1),
                expected_value=0.9,
            ),
        ),
    )


async def _complete_active(
    coordinator,
    journal: InMemoryCommandJournal,
    submitted,
) -> None:
    queued = await journal.get_command(submitted.eligible_command_id)
    assert queued is not None
    running = await journal.transition(
        queued.command_id,
        expected_version=queued.state_version,
        target=CommandState.RUNNING,
        reason_code="WORKER_CLAIMED",
        actor="worker",
        occurred_at_ms=1_100,
    )
    await journal.transition(
        queued.command_id,
        expected_version=running.state_version,
        target=CommandState.SUCCEEDED,
        reason_code="VERIFIED_SUCCESS",
        actor="controller",
        occurred_at_ms=1_101,
    )
    await coordinator.on_child_transition(
        _coordinator_module().VerifiedChildTransition(
            mission_id="showcase-001",
            objective_id=submitted.eligible_objective_id,
            command_id=queued.command_id,
            command_state="succeeded",
            verification="verified",
            evidence_refs=("observation:obs-adaptive-001",),
            occurred_at_ms=1_102,
        )
    )


async def test_autonomy_off_never_creates_curriculum_child() -> None:
    module = _coordinator_module()
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    coordinator = module.MissionCoordinator(repository=repository, journal=journal)
    mission = _fixed_mission()
    submitted = await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-off",
        spec=mission,
        occurred_at_ms=1_000,
    )

    result = await coordinator.consider_exploration(
        mission.mission_id,
        exploration=_exploration_input(),
        proposer=ExplorationProposer(ExplorationBounds(max_candidates=4, min_expected_value=0.5)),
        manifest=_manifest(("observe", "read_only")),
        occurred_at_ms=1_010,
    )

    snapshot = await repository.snapshot(mission.mission_id)
    assert result.exploration_outcome == "AUTONOMY_OFF"
    assert result.proposal_id is None
    assert snapshot.proposals == ()
    assert len((await journal.read_projection("conversation:user-001")).commands) == 1
    assert submitted.eligible_command_id is not None


async def test_committed_discovery_proposal_uses_admission_and_queues_once() -> None:
    module = _coordinator_module()
    repository = InMemoryMissionRepository()
    journal = InMemoryCommandJournal()
    coordinator = module.MissionCoordinator(repository=repository, journal=journal)
    payload = _mission_payload()
    payload["objectives"] = [payload["objectives"][0]]
    mission = MissionSpec.model_validate(payload)
    submitted = await coordinator.submit(
        caller_scope="conversation:user-001",
        request_id="request-bounded",
        spec=mission,
        occurred_at_ms=1_000,
    )
    await _complete_active(coordinator, journal, submitted)
    proposer = ExplorationProposer(ExplorationBounds(max_candidates=4, min_expected_value=0.5))

    admitted = await coordinator.consider_exploration(
        mission.mission_id,
        exploration=_exploration_input(),
        proposer=proposer,
        manifest=_manifest(("observe", "read_only")),
        occurred_at_ms=1_200,
    )
    repeated = await coordinator.consider_exploration(
        mission.mission_id,
        exploration=_exploration_input(),
        proposer=proposer,
        manifest=_manifest(("observe", "read_only")),
        occurred_at_ms=1_201,
    )

    snapshot = await repository.snapshot(mission.mission_id)
    assert admitted.admission_outcome == "accepted"
    assert admitted.eligible_command_id is not None
    assert snapshot.proposals[0].decision.reason_code == "ADMITTED"
    assert len(snapshot.objectives) == 2
    assert snapshot.objectives[-1].objective.goal.target == "minecraft:raw_copper"
    assert repeated.exploration_outcome == "OBSERVATION_ALREADY_CONSUMED"
    assert repeated.eligible_command_id == admitted.eligible_command_id
    assert len((await journal.read_projection("conversation:user-001")).commands) == 2
