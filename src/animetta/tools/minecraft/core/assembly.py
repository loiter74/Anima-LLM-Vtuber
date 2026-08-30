"""Lifecycle assembly for exactly one Minecraft Voyager control plane."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from animetta.tools.gamebot.contracts.v2 import ActionReceipt, RuntimeManifest
from animetta.tools.minecraft.discovery import (
    ExplorationBounds,
    ExplorationProposer,
    RuntimeDiscoveryProjector,
    SQLiteWorldFactStore,
)
from animetta.tools.minecraft.mission.adaptive import (
    AdaptiveMissionPolicy,
    ExplorationFrontier,
)
from animetta.tools.minecraft.mission.coordinator import (
    MissionCoordinator,
    VerifiedChildTransition,
)
from animetta.tools.minecraft.mission.events import ProjectionEventPublisher
from animetta.tools.minecraft.mission.projection import MissionProjectionService
from animetta.tools.minecraft.mission.repository import SQLiteMissionRepository
from animetta.tools.minecraft.mission.runtime import AdaptiveMissionRuntime
from animetta.tools.minecraft.skill.applicability import applicability_for_goal
from animetta.tools.minecraft.skill.independent_validation import (
    IndependentValidationEvidence,
)
from animetta.tools.minecraft.skill.ir import SkillDefinition
from animetta.tools.minecraft.skill.revision_store import SkillRevisionStore
from animetta.tools.minecraft.skill.trust import (
    ExecutionAttribution,
    SkillEnvironmentTrust,
    TrustStatus,
    stable_environment_fingerprint,
)
from animetta.tools.minecraft.survival.registry import WorkflowRegistry
from animetta.tools.minecraft.survival.workflows import (
    diamond_survival_workflow,
    iron_survival_workflow,
)
from animetta.tools.minecraft.tech_tree.graph import build_survival_tech_graph
from animetta.tools.minecraft.voyager.advancement_store import (
    AdvancementEventRecorder,
    SQLiteAdvancementEventStore,
)
from animetta.tools.minecraft.voyager.budget import (
    BudgetUsage,
    ExecutionBudget,
    ModeBudgetPolicy,
    budget_usage_from_vector,
)
from animetta.tools.minecraft.voyager.command_executor import CommandExecutor, ExecutorError
from animetta.tools.minecraft.voyager.command_models import (
    TERMINAL_COMMAND_STATES,
    CommandState,
    ControllerState,
)
from animetta.tools.minecraft.voyager.control_plane import (
    UnifiedVoyagerController,
    execution_budget_from_json,
)
from animetta.tools.minecraft.voyager.events import TransitionEventPublisher
from animetta.tools.minecraft.voyager.gateway import VoyagerGateway
from animetta.tools.minecraft.voyager.goal_evidence import RuntimeGoalEvidenceCollector
from animetta.tools.minecraft.voyager.goal_models import GoalSpec
from animetta.tools.minecraft.voyager.journal import JournalCommand
from animetta.tools.minecraft.voyager.public_activity import (
    PublicActivityEventPublisher,
    PublicActivityOutcome,
    PublicActivityRecorder,
    RuntimePublicActivityAggregator,
)
from animetta.tools.minecraft.voyager.scheduler import VoyagerCommandScheduler
from animetta.tools.minecraft.voyager.sqlite_repository import SQLiteCommandJournal
from animetta.tools.minecraft.voyager.stop import GlobalStopBarrier
from animetta.tools.minecraft.voyager.strategies.builtin import BuiltinMissionStrategy
from animetta.tools.minecraft.voyager.strategies.fallback import FallbackStrategy
from animetta.tools.minecraft.voyager.strategies.learn import LearnStrategy
from animetta.tools.minecraft.voyager.strategies.live import LiveStrategy
from animetta.tools.minecraft.voyager.strategies.mission import MissionStrategy

from .adapter import MinecraftGameBotV2Adapter
from .bridge import MinecraftMcpBridge
from .config import MinecraftConfig


def _now_ms() -> int:
    return int(time.time() * 1000)


def _make_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _budget_policy(config: MinecraftConfig) -> ModeBudgetPolicy:
    distance = float(config.safety.max_distance)

    def limits(
        actions: int,
        attempts: int,
        travel: float,
        blocks: int,
        execution_timeout_ms: int,
    ) -> ExecutionBudget:
        return ExecutionBudget(
            queue_timeout_ms=60_000,
            execution_timeout_ms=execution_timeout_ms,
            max_actions=actions,
            max_strategy_attempts=attempts,
            max_travel_distance=min(distance, travel),
            max_blocks_changed=blocks,
            max_damage_taken=8,
            protected_items=frozenset({"diamond_pickaxe", "netherite_pickaxe"}),
        )

    return ModeBudgetPolicy(
        atomic=limits(1, 1, 256, 32, 15 * 60_000),
        live=limits(32, 4, 256, 32, 15 * 60_000),
        fallback=limits(64, 4, 500, 512, 45 * 60_000),
        learn=limits(128, 8, 512, 1_024, 60 * 60_000),
    )


def _learning_frontier(goal: GoalSpec) -> tuple[str, ...]:
    if goal.intent == "acquire":
        source_block = goal.constraints.get("source_block")
        if isinstance(source_block, str) and source_block:
            item = goal.target.removeprefix("minecraft:")
            block = source_block.removeprefix("minecraft:")
            if all(
                part.replace("_", "").replace("-", "").replace(".", "").isalnum()
                for part in (item, block)
            ):
                return (f"acquire:{item}:{block}",)
    graph = build_survival_tech_graph()
    nodes = []
    for node_id in (
        "wood_collection",
        "crafting_table",
        "wooden_pickaxe",
        "cobblestone",
        "stone_pickaxe",
        "furnace",
        "iron_ingot",
        "iron_pickaxe",
        "diamond",
        "gold_ore",
    ):
        node = graph.get(node_id)
        nodes.append(node_id)
        if goal.target == node_id or goal.target in node.postconditions:
            return tuple(nodes)
    return ()


def _learning_proposal(node: str) -> dict:
    if node.startswith("acquire:"):
        _, item, block = node.split(":", 2)
        return {
            "node": node,
            "capability": "collect",
            "parameters": {"block_type": block, "count": 1},
            "maximum_cost": BudgetUsage(
                max_actions=1,
                max_travel_distance=64,
                max_blocks_changed=1,
                resource_consumption={},
            ),
            "acquired_item": item,
        }
    proposals = {
        "wood_collection": ("collect", {"block_type": "oak_log", "count": 1}),
        "crafting_table": ("craft", {"recipe": "crafting_table", "count": 1}),
        "wooden_pickaxe": ("craft", {"recipe": "wooden_pickaxe", "count": 1}),
        "cobblestone": ("collect", {"block_type": "stone", "count": 1}),
        "stone_pickaxe": ("craft", {"recipe": "stone_pickaxe", "count": 1}),
        "furnace": ("craft", {"recipe": "furnace", "count": 1}),
        "iron_ingot": ("smelt", {"item": "raw_iron", "fuel": "coal", "count": 1}),
        "iron_pickaxe": ("craft", {"recipe": "iron_pickaxe", "count": 1}),
        "diamond": ("collect", {"block_type": "diamond_ore", "count": 1}),
        "gold_ore": ("collect", {"block_type": "gold_ore", "count": 1}),
    }
    capability, parameters = proposals[node]
    return {
        "node": node,
        "capability": capability,
        "parameters": parameters,
        "maximum_cost": BudgetUsage(
            max_actions=1,
            max_travel_distance=64,
            max_blocks_changed=8,
        ),
    }


@dataclass
class MinecraftControlPlane:
    adapter: MinecraftGameBotV2Adapter
    repository: SQLiteCommandJournal
    skill_store: SkillRevisionStore
    executor: CommandExecutor
    controller: UnifiedVoyagerController
    scheduler: VoyagerCommandScheduler
    gateway: VoyagerGateway
    mission_repository: SQLiteMissionRepository
    mission_coordinator: MissionCoordinator
    mission_projection: MissionProjectionService
    world_fact_store: SQLiteWorldFactStore
    advancement_store: SQLiteAdvancementEventStore
    evidence_collector: RuntimeGoalEvidenceCollector
    adaptive_runtime: AdaptiveMissionRuntime | None
    activity_recorder: PublicActivityRecorder
    activity_aggregator: RuntimePublicActivityAggregator

    async def close(self) -> None:
        await self.repository.begin_shutdown(occurred_at_ms=_now_ms())
        await self.scheduler.stop()
        await self.activity_aggregator.drain()
        await self.repository.recover_startup(occurred_at_ms=_now_ms())
        await self.evidence_collector.drain()
        await self.advancement_store.close()
        await self.world_fact_store.close()
        await self.skill_store.close()
        await self.mission_repository.close()
        await self.repository.close()


async def assemble_control_plane(
    bridge: MinecraftMcpBridge,
    config: MinecraftConfig,
    *,
    event_emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    blueprint_origins: dict[str, tuple[int, int, int]] | None = None,
    entity_origins: dict[str, tuple[int, int, int]] | None = None,
    adaptive_frontier: ExplorationFrontier | None = None,
) -> MinecraftControlPlane:
    adapter = MinecraftGameBotV2Adapter(bridge)
    manifest = await adapter.get_manifest()
    repository = SQLiteCommandJournal(config.journal_path, queue_capacity=config.queue_capacity)
    await repository.connect()
    bridge_mode = getattr(bridge, "active_presentation_mode", None)
    presentation_mode = (
        bridge_mode
        if bridge_mode in {"off", "visual_only", "full"}
        else config.presentation.effective_mode
    )
    activity_enabled = presentation_mode != "off"
    await repository.expire_activity(
        before_ms=_now_ms() - config.presentation.retention_seconds * 1_000
    )
    mission_repository = SQLiteMissionRepository(config.journal_path)
    await mission_repository.connect()
    world_fact_store = SQLiteWorldFactStore(config.journal_path)
    await world_fact_store.connect()
    advancement_store = SQLiteAdvancementEventStore(config.journal_path)
    await advancement_store.connect()
    advancement_recorder = AdvancementEventRecorder(
        bridge=bridge,
        store=advancement_store,
    )
    if callable(getattr(bridge, "add_runtime_event_callback", None)):
        advancement_recorder.start()
    evidence_collector = RuntimeGoalEvidenceCollector(
        runtime=adapter,
        make_id=_make_id,
        now_ms=_now_ms,
        discovery_projector=RuntimeDiscoveryProjector(store=world_fact_store),
        world_fact_store=world_fact_store,
        advancement_store=advancement_store,
        advancement_recorder=advancement_recorder,
    )
    mission_coordinator = MissionCoordinator(
        repository=mission_repository,
        journal=repository,
    )
    mission_projection = MissionProjectionService(
        repository=mission_repository,
        journal=repository,
    )
    mission_events = ProjectionEventPublisher(emit=event_emit) if event_emit is not None else None
    startup_recovery = await repository.recover_startup(occurred_at_ms=_now_ms())
    if not startup_recovery.quarantined:
        await repository.begin_session(occurred_at_ms=_now_ms())
    event_publisher = (
        TransitionEventPublisher(repository=repository, emit=event_emit)
        if event_emit is not None
        else None
    )
    activity_publisher = (
        PublicActivityEventPublisher(emit=event_emit)
        if activity_enabled and event_emit is not None
        else None
    )
    activity_recorder = PublicActivityRecorder(
        repository=repository,
        enabled=activity_enabled,
        now_ms=_now_ms,
        publisher=activity_publisher,
        retention_ms=config.presentation.retention_seconds * 1_000,
    )
    activity_aggregator = RuntimePublicActivityAggregator(
        bridge=bridge,
        repository=repository,
        recorder=activity_recorder,
    )
    if activity_enabled and callable(getattr(bridge, "add_runtime_event_callback", None)):
        activity_aggregator.start()
    advanced_mission_commands: set[str] = set()
    adaptive_runtime: AdaptiveMissionRuntime | None = None

    async def notify(command_id: str) -> None:
        if event_publisher is not None:
            await event_publisher.publish_command(command_id)
        command = await repository.get_command(command_id)
        if command is not None:
            if command.state in {CommandState.QUEUED, CommandState.RUNNING}:
                await activity_recorder.record_command(
                    command,
                    source_key=f"{command.command_id}:planning",
                    phase="planning",
                )
            elif command.state is CommandState.RECONCILING:
                await activity_recorder.record_command(
                    command,
                    source_key=f"{command.command_id}:recovering",
                    phase="recovering",
                )
            elif command.state in TERMINAL_COMMAND_STATES:
                outcome: PublicActivityOutcome
                if command.state in {
                    CommandState.SUCCEEDED,
                    CommandState.SUCCEEDED_RECONCILED,
                }:
                    outcome = "succeeded"
                elif command.state in {
                    CommandState.CANCELLED,
                    CommandState.CANCELLED_RECONCILED,
                    CommandState.CANCELLED_BY_STOP,
                    CommandState.INTERRUPTED_BEFORE_START,
                }:
                    outcome = "cancelled"
                elif command.state is CommandState.BLOCKED_UNKNOWN:
                    outcome = "blocked"
                else:
                    outcome = "failed"
                await activity_recorder.record_command(
                    command,
                    source_key=f"{command.command_id}:finished:{command.state.value}",
                    phase="finished",
                    outcome=outcome,
                )
        if (
            command is None
            or command.mode != "mission"
            or command.state not in TERMINAL_COMMAND_STATES
            or command_id in advanced_mission_commands
        ):
            return
        mission_id = command.payload.get("mission_id")
        objective_id = command.payload.get("objective_id")
        if not isinstance(mission_id, str) or not isinstance(objective_id, str):
            return
        steps = await repository.list_steps(command_id)
        actual_budget = BudgetUsage()
        for step in steps:
            if step.receipt is None:
                continue
            receipt = ActionReceipt.model_validate(step.receipt)
            actual_budget = actual_budget.plus(budget_usage_from_vector(receipt.budget_usage))
        evidence_refs = tuple(
            f"receipt:{step.receipt['content_hash']}"
            for step in steps
            if step.receipt is not None and isinstance(step.receipt.get("content_hash"), str)
        ) or (f"command:{command_id}:{command.state.value}",)
        if command.state in {CommandState.SUCCEEDED, CommandState.SUCCEEDED_RECONCILED}:
            verification = "verified"
        elif command.state is CommandState.BLOCKED_UNKNOWN:
            verification = "unknown"
        else:
            verification = "failed"
        mission_advance = await mission_coordinator.on_child_transition(
            VerifiedChildTransition(
                mission_id=mission_id,
                objective_id=objective_id,
                command_id=command_id,
                command_state=command.state.value,
                verification=verification,
                evidence_refs=evidence_refs,
                actual_budget=actual_budget,
                occurred_at_ms=_now_ms(),
            )
        )
        advanced_mission_commands.add(command_id)
        if (
            adaptive_runtime is not None
            and mission_advance.mission_status.value == "waiting_evidence"
        ):
            await adaptive_runtime.after_child(
                mission_id=mission_id,
                command_id=command_id,
                occurred_at_ms=_now_ms(),
            )
        if mission_events is not None:
            page = await mission_projection.read(
                caller_scope=command.caller_scope,
                limit=100,
            )
            projection = next(item for item in page.missions if item.mission_id == mission_id)
            await mission_events.publish_mission(projection)

    skill_store = SkillRevisionStore(config.skill_path)
    await skill_store.connect()
    await skill_store.migrate_legacy_skills()
    executor = CommandExecutor(
        runtime=adapter,
        repository=repository,
        now_ms=_now_ms,
        make_id=_make_id,
        reconciliation_grace_seconds=config.cancellation_grace_seconds,
        activity_recorder=activity_recorder,
    )
    workflow_registry = WorkflowRegistry()
    workflow_registry.register(iron_survival_workflow())
    workflow_registry.register(diamond_survival_workflow())

    environment_fingerprint = stable_environment_fingerprint(manifest.profile)
    live_revisions, live_trusts = await skill_store.load_live_catalog(
        environment_fingerprint=environment_fingerprint
    )
    live_applicabilities = await skill_store.load_applicabilities()

    def fallback_factory(_manifest: RuntimeManifest, _command: JournalCommand) -> FallbackStrategy:
        return FallbackStrategy(registry=workflow_registry)

    def live_factory(current_manifest: RuntimeManifest, command: JournalCommand) -> LiveStrategy:
        execution_policy = command.payload.get("execution_policy", {})
        return LiveStrategy(
            revisions=live_revisions,
            applicabilities=live_applicabilities,
            trusts=live_trusts,
            manifest=current_manifest,
            allow_skill_reuse=(
                bool(execution_policy.get("reuse_trusted_skill", True))
                if isinstance(execution_policy, dict)
                else True
            ),
        )

    def learn_factory(current_manifest: RuntimeManifest, command: JournalCommand) -> LearnStrategy:
        return LearnStrategy(
            resolve_frontier=_learning_frontier,
            propose_node=_learning_proposal,
            max_frontier_nodes=4,
            max_attempts=2,
            manifest=current_manifest,
            compilation_budget=execution_budget_from_json(command.effective_budget),
            source_command_id=command.command_id,
        )

    def mission_factory(
        current_manifest: RuntimeManifest,
        command: JournalCommand,
    ) -> MissionStrategy:
        execution_policy = command.payload.get("execution_policy", {})
        policy = execution_policy if isinstance(execution_policy, dict) else {}
        return MissionStrategy(
            builtin=BuiltinMissionStrategy(
                manifest=current_manifest,
                blueprint_origins=blueprint_origins,
                entity_origins=entity_origins,
            ),
            live=(
                live_factory(current_manifest, command)
                if bool(policy.get("reuse_trusted_skill", True))
                else None
            ),
            learn=(
                learn_factory(current_manifest, command)
                if bool(policy.get("allow_skill_learning", False))
                else None
            ),
            fallback=(
                fallback_factory(current_manifest, command)
                if bool(policy.get("allow_deterministic_fallback", False))
                else None
            ),
        )

    async def persist_strategy_completion(
        *,
        command: JournalCommand,
        manifest: RuntimeManifest,
        output: dict[str, Any],
    ) -> None:
        if command.mode == "atomic":
            return
        selected_strategy = output.get("selected_strategy", command.mode)
        await evidence_collector.commit_goal(
            command.command_id,
            fallback_only=selected_strategy == "fallback",
        )
        if selected_strategy != "learn":
            return
        environment = stable_environment_fingerprint(manifest.profile)
        revisions = tuple(output.get("candidate_revisions", ()))
        validations = {
            evidence.revision_hash: evidence
            for evidence in output.get("independent_validations", ())
            if isinstance(evidence, IndependentValidationEvidence)
        }
        goal_payload = command.payload.get("goal")
        goal = (
            TypeAdapter(GoalSpec).validate_python(goal_payload)
            if goal_payload is not None
            else None
        )
        for revision in revisions:
            definition = SkillDefinition(
                definition_id=revision.definition_id,
                name=revision.program.name,
                description=f"Learned by {command.command_id}",
            )
            await skill_store.save_revision(definition, revision)
            if goal is not None:
                applicability = applicability_for_goal(revision, goal)
                await skill_store.save_applicability(applicability)
                live_applicabilities[revision.revision_hash] = applicability
            evidence = validations.get(revision.revision_hash)
            if evidence is not None:
                trust = await skill_store.record_independent_validation(
                    evidence.model_copy(update={"environment_fingerprint": environment}),
                    policy_report={
                        "valid": True,
                        "source_command_id": command.command_id,
                    },
                    expected_cost=float(revision.static_cost.max_actions),
                    portable=revision.program.portability.portable,
                )
            else:
                trust = SkillEnvironmentTrust(
                    revision_hash=revision.revision_hash,
                    environment_fingerprint=environment,
                    status=TrustStatus.CANDIDATE,
                    expected_cost=float(revision.static_cost.max_actions),
                    portable=revision.program.portability.portable,
                )
                await skill_store.record_validation(
                    trust,
                    policy_report={
                        "valid": False,
                        "reason": "MISSING_INDEPENDENT_VALIDATION_EVIDENCE",
                        "source_command_id": command.command_id,
                    },
                    learning_evidence=tuple(output.get("learning_evidence", ())),
                    validation_evidence=tuple(output.get("validation_evidence", ())),
                )
            live_revisions[revision.revision_hash] = revision
            live_trusts[:] = [
                item for item in live_trusts if item.revision_hash != revision.revision_hash
            ]
            live_trusts.append(trust)
            if event_emit is not None:
                with contextlib.suppress(Exception):
                    await event_emit(
                        {
                            "event": "minecraft.skill.trust",
                            "event_id": (f"trust:{revision.revision_hash}:{environment}"),
                            "revision_hash": revision.revision_hash,
                            "environment_fingerprint": environment,
                            "status": trust.status.value,
                            "source_command_id": command.command_id,
                        }
                    )

    async def persist_strategy_failure(
        *,
        command: JournalCommand,
        manifest: RuntimeManifest,
        state: dict[str, Any],
        error: Exception,
        receipt_hashes: tuple[str, ...],
    ) -> None:
        selected_strategy = state.get("selected_strategy", command.mode)
        strategy_state = state.get("strategy_state", state)
        if selected_strategy != "live" or strategy_state.get("revision") is None:
            return
        revision = strategy_state["revision"]
        environment = stable_environment_fingerprint(manifest.profile)
        current = next(
            (
                item
                for item in live_trusts
                if item.revision_hash == revision.revision_hash
                and item.environment_fingerprint == environment
            ),
            None,
        )
        if current is None:
            return
        attribution = ExecutionAttribution.ATTRIBUTABLE_FAILURE
        if isinstance(error, ExecutorError):
            if error.error.code in {
                "CAPABILITY_NOT_AUTHORIZED",
                "INVALID_CAPABILITY_PARAMETERS",
            }:
                attribution = ExecutionAttribution.POLICY_VIOLATION
            elif not error.error.outcome_known:
                attribution = ExecutionAttribution.RUNTIME_FAILURE
        updated = await skill_store.record_execution_outcome(
            execution_id=f"{command.command_id}:{revision.revision_hash[:16]}",
            trust=current,
            attribution=attribution,
            command_id=command.command_id,
            receipt_refs=receipt_hashes,
        )
        live_trusts[:] = [
            item
            for item in live_trusts
            if not (
                item.revision_hash == updated.revision_hash
                and item.environment_fingerprint == updated.environment_fingerprint
            )
        ]
        live_trusts.append(updated)
        if event_emit is not None:
            with contextlib.suppress(Exception):
                await event_emit(
                    {
                        "event": "minecraft.skill.trust",
                        "event_id": (
                            f"trust:{updated.revision_hash}:{environment}:"
                            f"{updated.successes}:{updated.failures}:{updated.status.value}"
                        ),
                        "revision_hash": updated.revision_hash,
                        "environment_fingerprint": environment,
                        "status": updated.status.value,
                        "source_command_id": command.command_id,
                        "attribution": attribution.value,
                    }
                )

    controller = UnifiedVoyagerController(
        runtime=adapter,
        repository=repository,
        executor=executor,
        strategy_factories={
            "fallback": fallback_factory,
            "live": live_factory,
            "learn": learn_factory,
            "mission": mission_factory,
        },
        evidence_collector=evidence_collector,
        make_id=_make_id,
        now_ms=_now_ms,
        on_strategy_complete=persist_strategy_completion,
        on_strategy_failed=persist_strategy_failure,
        activity_recorder=activity_recorder,
        initial_state=(
            ControllerState.QUARANTINED if startup_recovery.quarantined else ControllerState.IDLE
        ),
    )
    if adaptive_frontier is not None:

        def trusted_skill_snapshot(
            mission_id: str,
            environment: str,
        ) -> tuple[frozenset[str], frozenset[str]]:
            prefix = f"mission-{mission_id}-"
            trusted = frozenset(
                trust.revision_hash
                for trust in live_trusts
                if trust.environment_fingerprint == environment
                and trust.is_eligible(environment)
                and trust.revision_hash in live_revisions
                and live_revisions[trust.revision_hash].source_command_id.startswith(prefix)
            )
            technology = frozenset(
                live_revisions[revision_hash].definition_id for revision_hash in trusted
            )
            return trusted, technology

        adaptive_runtime = AdaptiveMissionRuntime(
            repository=mission_repository,
            coordinator=mission_coordinator,
            proposer=ExplorationProposer(
                ExplorationBounds(max_candidates=1, min_expected_value=0.5)
            ),
            manifest=manifest,
            policy=AdaptiveMissionPolicy(frontier=adaptive_frontier),
            evidence_collector=evidence_collector,
            trusted_skill_snapshot=trusted_skill_snapshot,
            controller_state=lambda: controller.state,
        )
    scheduler = VoyagerCommandScheduler(
        repository=repository,
        consumer=controller.execute_command,
        now_ms=_now_ms,
        on_command_changed=notify,
    )
    stop_barrier = GlobalStopBarrier(
        repository=repository,
        signal_active=controller.signal_cancel,
        now_ms=_now_ms,
        completion_timeout=config.reconciliation_timeout_seconds,
    )
    gateway = VoyagerGateway(
        repository=repository,
        stop_barrier=stop_barrier,
        manifest=manifest,
        budget_policy=_budget_policy(config),
        now_ms=_now_ms,
        make_id=_make_id,
        max_wait_seconds=config.max_tool_wait_seconds,
        on_command_changed=notify,
        execution_admitted=lambda: controller.state is not ControllerState.QUARANTINED,
        mission_coordinator=mission_coordinator,
        mission_projection=mission_projection,
        mission_events=mission_events,
        activity_enabled=activity_enabled,
        max_activity_replay=config.presentation.replay_limit,
    )
    result = MinecraftControlPlane(
        adapter=adapter,
        repository=repository,
        skill_store=skill_store,
        executor=executor,
        controller=controller,
        scheduler=scheduler,
        gateway=gateway,
        mission_repository=mission_repository,
        mission_coordinator=mission_coordinator,
        mission_projection=mission_projection,
        world_fact_store=world_fact_store,
        advancement_store=advancement_store,
        evidence_collector=evidence_collector,
        adaptive_runtime=adaptive_runtime,
        activity_recorder=activity_recorder,
        activity_aggregator=activity_aggregator,
    )
    scheduler.start()
    return result
