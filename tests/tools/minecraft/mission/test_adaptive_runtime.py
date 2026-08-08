from __future__ import annotations

from types import SimpleNamespace

from animetta.tools.gamebot.contracts.v2 import Observation, RuntimeManifest
from animetta.tools.minecraft.mission.adaptive import (
    AdaptiveMissionPolicy,
    ExplorationFrontier,
)
from animetta.tools.minecraft.mission.runtime import AdaptiveMissionRuntime
from animetta.tools.minecraft.mission.verifier import MissionEvidenceSnapshot
from animetta.tools.minecraft.voyager.command_models import ControllerState

from ..voyager.test_bounded_strategies import MESSAGES
from .test_models import _mission_payload


class _Coordinator:
    def __init__(self) -> None:
        self.exploration = None
        self.evidence = None

    async def consider_exploration(self, mission_id, **kwargs):
        self.exploration = (mission_id, kwargs)
        return SimpleNamespace(mission_status="running")

    async def verify_completion(self, mission_id, **kwargs):
        self.evidence = (mission_id, kwargs["evidence"])
        return SimpleNamespace(mission_status="completed")


class _Repository:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot

    async def snapshot(self, mission_id):
        assert mission_id == self._snapshot.mission.spec.mission_id
        return self._snapshot


class _Evidence:
    def __init__(self, observation, facts=(), advancements=()) -> None:
        self._record = SimpleNamespace(final=observation)
        self._facts = facts
        self._advancements = advancements

    def record(self, command_id):
        assert command_id == "mission-showcase-001-child-v1"
        return self._record

    async def current_world_facts(self, command_id):
        self.record(command_id)
        return self._facts

    async def current_advancement_events(self, command_id):
        self.record(command_id)
        return self._advancements


def _snapshot(*, phases=()):
    from animetta.tools.minecraft.mission.models import MissionSpec
    from animetta.tools.minecraft.mission.repository import MissionStatus

    payload = _mission_payload()
    payload["objectives"] = [payload["objectives"][0]]
    spec = MissionSpec.model_validate(payload)
    proposals = tuple(
        SimpleNamespace(
            decision=SimpleNamespace(outcome="accepted"),
            proposal=SimpleNamespace(goal=SimpleNamespace(constraints={"adaptive_phase": phase})),
        )
        for phase in phases
    )
    return SimpleNamespace(
        mission=SimpleNamespace(
            spec=spec,
            status=MissionStatus.WAITING_EVIDENCE,
            created_at_ms=100,
        ),
        proposals=proposals,
    )


def _runtime(
    repository,
    coordinator,
    evidence,
    trusted=(frozenset(), frozenset()),
):
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    return AdaptiveMissionRuntime(
        repository=repository,
        coordinator=coordinator,
        proposer=__import__(
            "animetta.tools.minecraft.discovery.exploration",
            fromlist=["ExplorationProposer"],
        ).ExplorationProposer(
            __import__(
                "animetta.tools.minecraft.discovery.exploration",
                fromlist=["ExplorationBounds"],
            ).ExplorationBounds(max_candidates=1, min_expected_value=0.5)
        ),
        manifest=manifest,
        policy=AdaptiveMissionPolicy(
            frontier=ExplorationFrontier(
                x=20,
                y=63,
                z=20,
                target_block="minecraft:copper_ore",
                target_item="minecraft:raw_copper",
            )
        ),
        evidence_collector=evidence,
        trusted_skill_snapshot=lambda _mission_id, _environment: trusted,
        controller_state=lambda: ControllerState.IDLE,
    )


async def test_runtime_admits_only_one_policy_child_from_waiting_evidence() -> None:
    observation = Observation.model_validate(MESSAGES["Observation"])
    snapshot = _snapshot()
    coordinator = _Coordinator()
    runtime = _runtime(_Repository(snapshot), coordinator, _Evidence(observation))

    result = await runtime.after_child(
        mission_id="showcase-001",
        command_id="mission-showcase-001-child-v1",
        occurred_at_ms=200,
    )

    assert result.action == "child_proposed"
    exploration = coordinator.exploration[1]["exploration"]
    assert len(exploration.unvisited_frontier) == 1
    assert coordinator.evidence is None


async def test_runtime_verifies_completion_only_after_reuse_phase() -> None:
    observation = Observation.model_validate(MESSAGES["Observation"])
    snapshot = _snapshot(phases=("explore", "learn_validate", "reuse"))
    coordinator = _Coordinator()
    runtime = _runtime(
        _Repository(snapshot),
        coordinator,
        _Evidence(observation),
        trusted=(frozenset({"a" * 64}), frozenset({"tech:raw-copper"})),
    )

    result = await runtime.after_child(
        mission_id="showcase-001",
        command_id="mission-showcase-001-child-v1",
        occurred_at_ms=200,
    )

    assert result.action == "verified"
    assert coordinator.exploration is None
    assert isinstance(coordinator.evidence[1], MissionEvidenceSnapshot)
    assert coordinator.evidence[1].trusted_skill_revision_hashes == frozenset({"a" * 64})
    assert coordinator.evidence[1].technology_evidence_ids == frozenset({"tech:raw-copper"})
