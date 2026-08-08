"""Production glue for evidence-driven adaptive mission continuation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from animetta.tools.gamebot.contracts.v2 import RuntimeManifest
from animetta.tools.minecraft.discovery.exploration import ExplorationProposer
from animetta.tools.minecraft.discovery.models import WorldFactState
from animetta.tools.minecraft.skill.trust import stable_environment_fingerprint
from animetta.tools.minecraft.voyager.command_models import ControllerState
from animetta.tools.minecraft.voyager.goal_evidence import RuntimeGoalEvidenceCollector

from .adaptive import AdaptiveMissionPolicy, AdaptiveMissionState
from .coordinator import MissionCoordinator
from .repository import MissionStatus
from .verifier import MissionEvidenceSnapshot


class AdaptiveRuntimeResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    action: Literal["ignored", "child_proposed", "verified", "stopped"]
    coordinator_result: Any | None = None
    stop_reason: str | None = None


def _resource_id(value: str) -> str:
    return value if ":" in value else f"minecraft:{value}"


class AdaptiveMissionRuntime:
    """Continue a waiting mission from durable evidence, one child at a time."""

    def __init__(
        self,
        *,
        repository: Any,
        coordinator: MissionCoordinator,
        proposer: ExplorationProposer,
        manifest: RuntimeManifest,
        policy: AdaptiveMissionPolicy,
        evidence_collector: RuntimeGoalEvidenceCollector,
        trusted_skill_snapshot: Callable[[str, str], tuple[frozenset[str], frozenset[str]]],
        controller_state: Callable[[], ControllerState],
    ) -> None:
        self._repository = repository
        self._coordinator = coordinator
        self._proposer = proposer
        self._manifest = manifest
        self._policy = policy
        self._evidence_collector = evidence_collector
        self._trusted_skill_snapshot = trusted_skill_snapshot
        self._controller_state = controller_state

    async def after_child(
        self,
        *,
        mission_id: str,
        command_id: str,
        occurred_at_ms: int,
    ) -> AdaptiveRuntimeResult:
        snapshot = await self._repository.snapshot(mission_id)
        if snapshot.mission.status is not MissionStatus.WAITING_EVIDENCE:
            return AdaptiveRuntimeResult(action="ignored")

        record = self._evidence_collector.record(command_id)
        environment = stable_environment_fingerprint(record.final.profile)
        trusted, technology = self._trusted_skill_snapshot(mission_id, environment)
        facts = await self._evidence_collector.current_world_facts(command_id)
        advancements = await self._evidence_collector.current_advancement_events(command_id)
        acquired = frozenset(
            fact.fact_id
            for fact in facts
            if fact.state is WorldFactState.ACQUIRED
            and (fact.acquisition_command_ref or "").startswith(f"command:mission-{mission_id}-")
        )
        advancement_ids = frozenset(
            event.advancement_id
            for event in advancements
            if event.action == "add" and event.observed_at_ms >= snapshot.mission.created_at_ms
        )
        phases = frozenset(
            phase
            for item in snapshot.proposals
            if item.decision.outcome == "accepted"
            for phase in (item.proposal.goal.constraints.get("adaptive_phase"),)
            if phase in {"explore", "learn_validate", "reuse"}
        )
        inventory = {_resource_id(item): count for item, count in record.final.inventory.items()}
        decision = self._policy.decide(
            AdaptiveMissionState(
                mission_id=mission_id,
                observation_ref=f"observation:{record.final.observation_id}",
                observed_fact_keys=frozenset(
                    f"{fact.identity.fact_kind}:{fact.identity.fact_key}" for fact in facts
                ),
                acquired_fact_ids=acquired,
                trusted_revision_hashes=trusted,
                inventory=inventory,
                completed_adaptive_phases=phases,
            )
        )
        if decision.ready_for_verification:
            result = await self._coordinator.verify_completion(
                mission_id,
                evidence=MissionEvidenceSnapshot(
                    acquired_world_fact_ids=acquired,
                    trusted_skill_revision_hashes=trusted,
                    vanilla_advancement_ids=advancement_ids,
                    technology_evidence_ids=technology,
                ),
                occurred_at_ms=occurred_at_ms,
            )
            return AdaptiveRuntimeResult(action="verified", coordinator_result=result)
        if decision.exploration is None:
            return AdaptiveRuntimeResult(
                action="stopped",
                stop_reason=decision.stop_reason,
            )
        result = await self._coordinator.consider_exploration(
            mission_id,
            exploration=decision.exploration,
            proposer=self._proposer,
            manifest=self._manifest,
            occurred_at_ms=occurred_at_ms,
            runtime_quarantined=(self._controller_state() is ControllerState.QUARANTINED),
        )
        return AdaptiveRuntimeResult(action="child_proposed", coordinator_result=result)
