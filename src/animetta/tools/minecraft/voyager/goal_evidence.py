"""Typed evidence gathered independently of strategy completion claims."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from animetta.tools.gamebot.contracts.v2 import (
    ActionReceipt,
    AdvancementObservedEvent,
    Observation,
    RegionInspection,
    RegionInspectionRequest,
    RuntimeManifest,
)
from animetta.tools.minecraft.blueprint.models import CompiledBlueprint
from animetta.tools.minecraft.discovery.models import WorldFact
from animetta.tools.minecraft.discovery.runtime import (
    RuntimeDiscoveryProjector,
    RuntimeDiscoveryResult,
)
from animetta.tools.minecraft.discovery.store import WorldFactStore
from animetta.tools.minecraft.skill.trust import stable_environment_fingerprint

from .advancement_store import AdvancementEventRecorder, AdvancementEventStore
from .goal_models import GoalSpec
from .journal import JournalCommand


class GoalEvidence(BaseModel):
    """Closed evidence envelope supplied to ``GoalVerifier``."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    compiled_blueprints: tuple[CompiledBlueprint, ...] = ()
    region_inspections: tuple[RegionInspection, ...] = ()
    world_facts: tuple[WorldFact, ...] = ()
    advancement_events: tuple[AdvancementObservedEvent, ...] = ()
    technology_evidence: tuple[Any, ...] = ()

    def verifier_arguments(self) -> dict[str, object]:
        return {
            "compiled_blueprints": self.compiled_blueprints,
            "region_inspections": self.region_inspections,
            "world_facts": self.world_facts,
            "advancement_events": self.advancement_events,
            "technology_evidence": self.technology_evidence,
        }


class RuntimeCommandEvidence(BaseModel):
    """Execution evidence retained until the verified goal is durably projected."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    command: JournalCommand
    manifest: RuntimeManifest
    goal: GoalSpec
    initial: Observation
    final: Observation
    receipts: tuple[ActionReceipt, ...]
    output: dict[str, Any]
    goal_evidence: GoalEvidence
    committed: bool = False
    discovery: RuntimeDiscoveryResult = RuntimeDiscoveryResult()


class GoalEvidenceCollector(Protocol):
    async def collect(
        self,
        *,
        command: JournalCommand,
        manifest: RuntimeManifest,
        goal: GoalSpec,
        initial: Observation,
        final: Observation,
        receipts: tuple[ActionReceipt, ...],
        output: dict[str, Any],
    ) -> GoalEvidence: ...


class EmptyGoalEvidenceCollector:
    async def collect(self, **kwargs: object) -> GoalEvidence:
        del kwargs
        return GoalEvidence()


class RuntimeGoalEvidenceCollector:
    """Gather bounded read-only evidence after strategy completion."""

    def __init__(
        self,
        *,
        runtime: Any,
        make_id: Callable[[str], str],
        now_ms: Callable[[], int],
        discovery_projector: RuntimeDiscoveryProjector | None = None,
        world_fact_store: WorldFactStore | None = None,
        advancement_store: AdvancementEventStore | None = None,
        advancement_recorder: AdvancementEventRecorder | None = None,
    ) -> None:
        self._runtime = runtime
        self._make_id = make_id
        self._now_ms = now_ms
        self._discovery_projector = discovery_projector
        self._world_fact_store = world_fact_store
        self._advancement_store = advancement_store
        self._advancement_recorder = advancement_recorder
        self._records: dict[str, RuntimeCommandEvidence] = {}

    def record(self, command_id: str) -> RuntimeCommandEvidence:
        return self._records[command_id].model_copy(deep=True)

    def environment_fingerprint(self, command_id: str) -> str:
        return stable_environment_fingerprint(self._records[command_id].final.profile)

    async def drain(self) -> None:
        if self._advancement_recorder is not None:
            await self._advancement_recorder.drain()

    async def current_world_facts(self, command_id: str) -> tuple[WorldFact, ...]:
        if self._world_fact_store is None:
            return ()
        record = self._records.get(command_id)
        if record is None:
            return ()
        return await self._world_fact_store.list_scope(
            world_identity_hash=record.final.profile.world_identity_hash,
            environment_fingerprint=stable_environment_fingerprint(record.final.profile),
        )

    async def current_advancement_events(
        self, command_id: str
    ) -> tuple[AdvancementObservedEvent, ...]:
        if self._advancement_recorder is not None:
            await self._advancement_recorder.drain()
        if self._advancement_store is None:
            return ()
        record = self._records.get(command_id)
        if record is None:
            return ()
        return await self._advancement_store.list_scope(
            world_identity_hash=record.final.profile.world_identity_hash,
            runtime_instance_id=record.final.runtime_instance_id,
        )

    async def commit_goal(self, command_id: str, *, fallback_only: bool) -> RuntimeDiscoveryResult:
        record = self._records[command_id]
        if record.committed:
            return record.discovery
        discovery = RuntimeDiscoveryResult()
        if self._discovery_projector is not None:
            discovery = await self._discovery_projector.project_goal(
                goal=record.goal,
                command_id=command_id,
                initial=record.initial,
                final=record.final,
                receipts=record.receipts,
                fallback_only=fallback_only,
            )
        self._records[command_id] = record.model_copy(
            update={"committed": True, "discovery": discovery}
        )
        return discovery

    async def collect(
        self,
        *,
        command: JournalCommand,
        manifest: RuntimeManifest,
        goal: GoalSpec,
        initial: Observation,
        final: Observation,
        receipts: tuple[ActionReceipt, ...],
        output: dict[str, Any],
    ) -> GoalEvidence:
        compiled = tuple(
            item
            for item in output.get("compiled_blueprints", ())
            if isinstance(item, CompiledBlueprint)
        )
        inspections: list[RegionInspection] = []
        for blueprint in compiled:
            inspections.append(
                await self._runtime.inspect_region(
                    RegionInspectionRequest(
                        transport_id=self._make_id("transport"),
                        command_id=command.command_id,
                        step_id=self._make_id("inspection-step"),
                        correlation_id=self._make_id("inspection-correlation"),
                        runtime_instance_id=manifest.runtime_instance_id,
                        bounds=blueprint.bounds,
                        maximum_volume=blueprint.bounds.volume,
                        deadline_ms=command.execution_deadline_ms or self._now_ms() + 10_000,
                    )
                )
            )
        environment = stable_environment_fingerprint(final.profile)
        world_facts: tuple[WorldFact, ...] = ()
        if self._world_fact_store is not None:
            world_facts = await self._world_fact_store.list_scope(
                world_identity_hash=final.profile.world_identity_hash,
                environment_fingerprint=environment,
            )
        if self._advancement_recorder is not None:
            await self._advancement_recorder.drain()
        advancement_events: tuple[AdvancementObservedEvent, ...] = ()
        if self._advancement_store is not None:
            advancement_events = await self._advancement_store.list_scope(
                world_identity_hash=final.profile.world_identity_hash,
                runtime_instance_id=final.runtime_instance_id,
            )
        evidence = GoalEvidence(
            compiled_blueprints=compiled,
            region_inspections=tuple(inspections),
            world_facts=world_facts,
            advancement_events=advancement_events,
        )
        self._records[command.command_id] = RuntimeCommandEvidence(
            command=command,
            manifest=manifest,
            goal=goal,
            initial=initial,
            final=final,
            receipts=receipts,
            output=output,
            goal_evidence=evidence,
        )
        return evidence
