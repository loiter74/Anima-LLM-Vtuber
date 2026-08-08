"""The controller gathers authoritative evidence before declaring a goal complete."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from animetta.tools.gamebot.contracts.v2 import ActionReceipt, Observation, RuntimeManifest
from animetta.tools.minecraft.blueprint import (
    BlueprintBinding,
    BlueprintCompiler,
    starter_shelter_blueprint,
)
from animetta.tools.minecraft.discovery import (
    InMemoryWorldFactStore,
    RuntimeDiscoveryProjector,
    WorldFactState,
)
from animetta.tools.minecraft.voyager.budget import ExecutionBudget
from animetta.tools.minecraft.voyager.command_executor import (
    ExecutorError,
    ReconciliationResult,
)
from animetta.tools.minecraft.voyager.command_models import (
    CommandState,
    ControlPlaneError,
)
from animetta.tools.minecraft.voyager.control_plane import UnifiedVoyagerController
from animetta.tools.minecraft.voyager.goal_evidence import (
    GoalEvidence,
    RuntimeGoalEvidenceCollector,
)
from animetta.tools.minecraft.voyager.goal_models import GoalSpec
from animetta.tools.minecraft.voyager.journal import JournalCommand
from animetta.tools.minecraft.voyager.reconciliation import RecoveryDecision
from animetta.tools.minecraft.voyager.scheduler import CommandExecutionError
from animetta.tools.minecraft.voyager.strategies.base import Complete

ROOT = Path(__file__).resolve().parents[4]
MESSAGES = json.loads(
    (ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8")
)["messages"]


class RuntimeStub:
    runtime_instance_id = "runtime-instance-1"
    is_running = True

    def __init__(self) -> None:
        self.manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
        self.observation = Observation.model_validate(MESSAGES["Observation"])

    async def get_manifest(self):
        return self.manifest

    async def observe(self, request):
        del request
        return self.observation


class ExecutorStub:
    def set_dispatch_observer(self, observer):
        self.observer = observer


class CompleteStrategy:
    def prepare(self, goal):
        return {"goal": goal}

    def propose(self, state, observation):
        del state, observation
        return Complete(output={"compiled_blueprints": ()})

    def accept_result(self, state, result):  # pragma: no cover - no steps
        raise AssertionError((state, result))


class EvidenceCollectorStub:
    def __init__(self) -> None:
        self.called = False

    async def collect(self, **kwargs):
        assert kwargs["output"] == {"compiled_blueprints": ()}
        self.called = True
        return GoalEvidence(technology_evidence=("technology:stone-age",))


class VerifierStub:
    def __init__(self) -> None:
        self.received = None

    def verify(self, **kwargs):
        self.received = kwargs
        return {"satisfied": True, "predicate_results": [], "evidence_hashes": []}


def _goal():
    return TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "survive",
            "target": "stay healthy",
            "success_predicates": [{"kind": "health_at_least", "health": 1}],
        }
    )


def _command() -> JournalCommand:
    budget = ExecutionBudget(
        queue_timeout_ms=1_000,
        execution_timeout_ms=10_000,
        max_actions=1,
        max_strategy_attempts=1,
        max_travel_distance=1,
        max_blocks_changed=0,
        max_damage_taken=0,
    )
    return JournalCommand(
        command_id="mission-m1-objective-v1",
        caller_scope="session:one",
        request_id="request-1",
        request_hash="a" * 64,
        kind="execute",
        mode="mission",
        payload={"goal": _goal().model_dump(mode="json")},
        requested_budget=budget.model_dump(mode="json"),
        effective_budget=budget.model_dump(mode="json"),
        accepted_at_ms=1,
        queue_deadline_ms=2_000,
        execution_deadline_ms=10_000,
        queue_sequence=1,
        state=CommandState.RUNNING,
        state_version=2,
        started_at_ms=2,
    )


async def test_missing_failed_command_has_empty_projected_evidence() -> None:
    collector = RuntimeGoalEvidenceCollector(
        runtime=object(),
        make_id=lambda prefix: f"{prefix}-id",
        now_ms=lambda: 1,
        world_fact_store=object(),
        advancement_store=object(),
    )

    assert await collector.current_world_facts("failed-before-evidence") == ()
    assert await collector.current_advancement_events("failed-before-evidence") == ()


async def test_controller_passes_collected_typed_evidence_to_goal_verifier() -> None:
    collector = EvidenceCollectorStub()
    verifier = VerifierStub()
    controller = UnifiedVoyagerController(
        runtime=RuntimeStub(),
        repository=object(),
        executor=ExecutorStub(),
        strategy_factories={"mission": lambda _manifest, _command: CompleteStrategy()},
        verifier=verifier,
        evidence_collector=collector,
        make_id=lambda prefix: f"{prefix}-id",
        now_ms=lambda: 10,
    )

    await controller.execute_command(_command())

    assert collector.called is True
    assert verifier.received["technology_evidence"] == ("technology:stone-age",)


async def test_goal_verification_failure_retains_auditable_evidence() -> None:
    class FailingVerifier:
        def verify(self, **_kwargs):
            return {
                "satisfied": False,
                "predicate_results": [
                    {
                        "kind": "health_at_least",
                        "satisfied": False,
                        "evidence_hash": "e" * 64,
                    }
                ],
                "evidence_hashes": ["e" * 64],
            }

    controller = UnifiedVoyagerController(
        runtime=RuntimeStub(),
        repository=object(),
        executor=ExecutorStub(),
        strategy_factories={"mission": lambda _manifest, _command: CompleteStrategy()},
        verifier=FailingVerifier(),
        evidence_collector=EvidenceCollectorStub(),
        make_id=lambda prefix: f"{prefix}-id",
        now_ms=lambda: 10,
    )

    with pytest.raises(CommandExecutionError) as caught:
        await controller.execute_command(_command())

    error = caught.value
    assert error.reason_code == "GOAL_VERIFICATION_FAILED"
    assert error.details["verification"]["predicate_results"][0]["satisfied"] is False
    assert error.terminal_result is not None
    assert error.terminal_result["error"]["code"] == "GOAL_VERIFICATION_FAILED"
    assert error.terminal_result["output"]["goal_evidence"]["technology_evidence"] == [
        "technology:stone-age"
    ]


async def test_blocked_unknown_retains_reconciliation_quarantine_evidence() -> None:
    receipt = ActionReceipt.model_validate(MESSAGES["ActionReceipt"])
    recovery_details = {
        "mutations_explained": False,
        "observable_state_diff": {
            "inventory": {
                "receipt_after": {"oak_log": 1},
                "fresh_observation": {"oak_log": 2},
            }
        },
    }

    class UnknownExecutor(ExecutorStub):
        async def reconcile_unknown(self, **_kwargs):
            return ReconciliationResult(
                RecoveryDecision.BLOCKED_UNKNOWN,
                recovery_details,
                receipt=receipt,
            )

    controller = UnifiedVoyagerController(
        runtime=RuntimeStub(),
        repository=object(),
        executor=UnknownExecutor(),
        strategy_factories={"mission": lambda _manifest, _command: CompleteStrategy()},
        verifier=VerifierStub(),
        evidence_collector=EvidenceCollectorStub(),
        make_id=lambda prefix: f"{prefix}-id",
        now_ms=lambda: 10,
    )

    async def fail_with_unknown(_command):
        raise ExecutorError(
            ControlPlaneError(
                code="RUNTIME_RESPONSE_LOST",
                message="response lost after possible mutation",
                phase="recovery",
                outcome_known=False,
                world_may_have_changed=True,
                caller_may_resubmit=False,
                operator_action="inspect quarantined evidence",
            )
        )

    controller._execute_active = fail_with_unknown

    with pytest.raises(CommandExecutionError) as caught:
        await controller.execute_command(_command())

    error = caught.value
    assert error.terminal_state is CommandState.BLOCKED_UNKNOWN
    assert error.terminal_result is not None
    assert error.terminal_result["receipt_ids"] == [receipt.receipt_id]
    assert error.terminal_result["output"]["reconciliation"] == recovery_details
    assert error.terminal_result["error"]["details"] == recovery_details


async def test_runtime_collector_inspects_the_exact_compiled_blueprint_region() -> None:
    runtime = RuntimeStub()
    requests = []

    async def inspect_region(request):
        requests.append(request)
        payload = {
            "schema_version": "2",
            "inspection_id": "inspection-1",
            "correlation_id": request.correlation_id,
            "runtime_instance_id": runtime.runtime_instance_id,
            "world_identity": runtime.observation.world_identity.model_dump(mode="json"),
            "captured_at_ms": 11,
            "tick": 11,
            "observation_id": runtime.observation.observation_id,
            "observation_hash": runtime.observation.content_hash,
            "bounds": request.bounds.model_dump(mode="json"),
            "blocks": {},
            "content_hash": "b" * 64,
        }
        from animetta.tools.gamebot.contracts.v2 import RegionInspection

        return RegionInspection.model_validate(payload)

    runtime.inspect_region = inspect_region
    compiled = BlueprintCompiler().compile(
        starter_shelter_blueprint(),
        BlueprintBinding(origin=(4, 65, 4), materials={}),
    )
    collector = RuntimeGoalEvidenceCollector(
        runtime=runtime,
        make_id=lambda prefix: f"{prefix}-id",
        now_ms=lambda: 10,
    )

    evidence = await collector.collect(
        command=_command(),
        manifest=runtime.manifest,
        goal=_goal(),
        initial=runtime.observation,
        final=runtime.observation,
        receipts=(),
        output={"compiled_blueprints": (compiled,)},
    )

    assert len(requests) == 1
    assert requests[0].bounds == compiled.bounds
    assert requests[0].maximum_volume == compiled.bounds.volume
    assert evidence.region_inspections[0].bounds == compiled.bounds


async def test_runtime_collector_commits_discovery_only_after_goal_verification() -> None:
    runtime = RuntimeStub()
    store = InMemoryWorldFactStore()
    await store.connect()
    collector = RuntimeGoalEvidenceCollector(
        runtime=runtime,
        make_id=lambda prefix: f"{prefix}-id",
        now_ms=lambda: 10,
        discovery_projector=RuntimeDiscoveryProjector(store=store),
        world_fact_store=store,
    )
    initial = runtime.observation.model_copy(update={"inventory": {}})
    final_payload = runtime.observation.model_dump(mode="json")
    final_payload["inventory"] = {"raw_copper": 1}
    final_payload["visible_blocks"] = [
        {
            "block_id": "minecraft:copper_ore",
            "position": {"x": 20, "y": 63, "z": 20},
        }
    ]
    final = Observation.model_validate(final_payload)
    receipt = ActionReceipt.model_validate(MESSAGES["ActionReceipt"]).model_copy(
        update={
            "command_id": _command().command_id,
            "explained_mutations": (
                ActionReceipt.model_validate(MESSAGES["ActionReceipt"])
                .explained_mutations[0]
                .model_copy(update={"subject": "raw_copper", "delta": 1}),
            ),
        }
    )
    acquire = TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "acquire",
            "target": "minecraft:raw_copper",
            "constraints": {"source_block": "minecraft:copper_ore"},
            "success_predicates": [
                {
                    "kind": "inventory_at_least",
                    "item": "minecraft:raw_copper",
                    "quantity": 1,
                }
            ],
        }
    )

    await collector.collect(
        command=_command(),
        manifest=runtime.manifest,
        goal=acquire,
        initial=initial,
        final=final,
        receipts=(receipt,),
        output={"selected_strategy": "learn"},
    )
    before = await store.list_scope(
        world_identity_hash=final.profile.world_identity_hash,
        environment_fingerprint=collector.environment_fingerprint(_command().command_id),
    )
    committed = await collector.commit_goal(_command().command_id, fallback_only=False)
    after = await store.list_scope(
        world_identity_hash=final.profile.world_identity_hash,
        environment_fingerprint=collector.environment_fingerprint(_command().command_id),
        state=WorldFactState.ACQUIRED,
    )

    assert before == ()
    assert {fact.identity.fact_key for fact in committed.observed} >= {
        "minecraft:copper_ore",
        "minecraft:raw_copper",
    }
    assert [fact.identity.fact_key for fact in after] == ["minecraft:raw_copper"]
    assert collector.record(_command().command_id).committed is True
