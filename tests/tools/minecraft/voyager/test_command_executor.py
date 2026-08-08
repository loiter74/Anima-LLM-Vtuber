"""The command executor is the sole Python state-changing runtime caller."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from animetta.tools.gamebot.contracts.v2 import (
    ActionReceipt,
    ActionStatus,
    CancellationAck,
    Observation,
    RuntimeHealth,
    RuntimeManifest,
    canonical_json_hash,
)
from animetta.tools.minecraft.blueprint import starter_shelter_blueprint
from animetta.tools.minecraft.voyager.budget import BudgetAccount, BudgetUsage, ExecutionBudget
from animetta.tools.minecraft.voyager.command_executor import (
    CommandExecutor,
    ExecutorError,
    ReconciliationResult,
)
from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.control_plane import _reconciled_terminal_for_command
from animetta.tools.minecraft.voyager.goal_verifier import GoalVerifier
from animetta.tools.minecraft.voyager.journal import CommandDraft, InMemoryCommandJournal
from animetta.tools.minecraft.voyager.reconciliation import RecoveryDecision
from animetta.tools.minecraft.voyager.strategies.base import ExecuteStep

ROOT = Path(__file__).resolve().parents[4]
MESSAGES = json.loads(
    (ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8")
)["messages"]


def budget() -> ExecutionBudget:
    return ExecutionBudget(
        queue_timeout_ms=1_000,
        execution_timeout_ms=10_000,
        max_actions=4,
        max_strategy_attempts=2,
        max_travel_distance=64,
        max_blocks_changed=8,
        max_damage_taken=4,
    )


async def command(repository: InMemoryCommandJournal):
    created = (
        await repository.create_command(
            CommandDraft(
                command_id="command-1",
                caller_scope="principal:a",
                request_id="request-1",
                request_hash="a" * 64,
                kind="execute",
                mode="atomic",
                payload={},
                requested_budget={},
                effective_budget={},
                accepted_at_ms=1,
                execution_deadline_ms=2_000_000_000_000,
            )
        )
    )[0]
    return await repository.transition(
        created.command_id,
        expected_version=0,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="worker",
        occurred_at_ms=2,
    )


class Runtime:
    def __init__(self, repository: InMemoryCommandJournal) -> None:
        self.repository = repository
        self.manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
        self.requests = []

    async def get_manifest(self):
        return self.manifest

    async def execute_action(self, request, *, timeout=60.0):
        self.requests.append(request)
        reserved = await self.repository.get_step(request.step_id)
        assert reserved is not None and reserved.state == "dispatched"
        payload = dict(MESSAGES["ActionReceipt"])
        payload.update(
            {
                "command_id": request.command_id,
                "step_id": request.step_id,
                "correlation_id": request.correlation_id,
                "runtime_instance_id": request.runtime_instance_id,
                "capability": request.capability,
                "parameter_hash": request.canonical_parameters_hash,
                "previous_receipt_hash": request.previous_receipt_hash,
                "budget_usage": {
                    "max_actions": 1,
                    "max_strategy_attempts": 0,
                    "max_travel_distance": 2,
                    "max_blocks_changed": 1,
                    "max_damage_taken": 0,
                    "protected_items": [],
                    "resource_consumption": {},
                },
                "explained_mutations": [
                    {
                        "kind": "other",
                        "subject": "observable_state",
                        "delta": None,
                        "details": {
                            "before_state": {
                                "position": {"x": 0, "y": 64, "z": 0},
                                "health": 20,
                                "food": 20,
                                "inventory": {"oak_log": 1},
                                "equipment": {},
                                "environment": {},
                            },
                            "after_state": {
                                "position": {"x": 0, "y": 64, "z": 0},
                                "health": 20,
                                "food": 20,
                                "inventory": {"oak_log": 1},
                                "equipment": {},
                                "environment": {},
                            },
                            "before_state_hash": canonical_json_hash(
                                {
                                    "position": {"x": 0, "y": 64, "z": 0},
                                    "health": 20,
                                    "food": 20,
                                    "inventory": {"oak_log": 1},
                                    "equipment": {},
                                    "environment": {},
                                }
                            ),
                            "after_state_hash": canonical_json_hash(
                                {
                                    "position": {"x": 0, "y": 64, "z": 0},
                                    "health": 20,
                                    "food": 20,
                                    "inventory": {"oak_log": 1},
                                    "equipment": {},
                                    "environment": {},
                                }
                            ),
                        },
                    }
                ],
            }
        )
        payload["content_hash"] = canonical_json_hash(
            {key: value for key, value in payload.items() if key != "content_hash"}
        )
        return ActionReceipt.model_validate(payload)

    async def observe(self, request):
        payload = dict(MESSAGES["Observation"])
        payload.update(
            {
                "correlation_id": request.correlation_id,
                "runtime_instance_id": request.runtime_instance_id,
                "action_sequence": 9,
            }
        )
        payload["content_hash"] = canonical_json_hash(
            {key: value for key, value in payload.items() if key != "content_hash"}
        )
        return Observation.model_validate(payload)


def test_grounded_motion_settlement_accepts_only_bounded_gravity_remainder() -> None:
    observation = Observation.model_validate(MESSAGES["Observation"])

    def with_vertical_velocity(vertical: float) -> Observation:
        return observation.model_copy(
            update={
                "environment": {
                    **observation.environment,
                    "on_ground": True,
                    "velocity": {"x": 0, "y": vertical, "z": 0},
                }
            },
            deep=True,
        )

    assert CommandExecutor._observation_motion_settled(with_vertical_velocity(-0.0784000015))
    assert not CommandExecutor._observation_motion_settled(with_vertical_velocity(-2.0))
    assert not CommandExecutor._observation_motion_settled(with_vertical_velocity(0.25))


async def test_executor_reserves_before_dispatch_validates_receipt_and_observes_after() -> None:
    repository = InMemoryCommandJournal()
    runtime = Runtime(repository)
    executor = CommandExecutor(
        runtime=runtime,
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
    )
    cmd = await command(repository)
    before = Observation.model_validate(MESSAGES["Observation"])
    step = ExecuteStep(
        capability="collect",
        parameters={"count": 1},
        maximum_cost=BudgetUsage(max_actions=1, max_travel_distance=16, max_blocks_changed=4),
    )

    result = await executor.execute_step(
        command=cmd,
        step=step,
        before=before,
        ordinal=1,
        strategy_state_hash="b" * 64,
        account=BudgetAccount(limit=budget()),
    )

    persisted = await repository.get_step("step-1")
    facts = await repository.command_facts(cmd.command_id)
    assert persisted is not None and persisted.state == "settled"
    assert facts["checkpoints"] == 1
    assert result.account.remaining.max_actions == 3
    assert result.after.action_sequence >= result.receipt.action_sequence


async def test_executor_does_not_settle_successful_receipt_with_pending_reconciliation() -> None:
    repository = InMemoryCommandJournal()

    class PendingReconciliationRuntime(Runtime):
        async def execute_action(self, request, *, timeout=60.0):
            receipt = await super().execute_action(request, timeout=timeout)
            payload = receipt.model_dump(mode="json", exclude={"content_hash"})
            reconciliation_error = dict(MESSAGES["RuntimeProtocolError"])
            reconciliation_error.update(
                {
                    "code": "POST_ACTION_OBSERVATION_UNSTABLE",
                    "message": "post-action state did not settle",
                    "command_id": request.command_id,
                    "step_id": request.step_id,
                    "correlation_id": request.correlation_id,
                    "outcome_known": False,
                    "world_may_have_changed": True,
                    "operator_action": "reconcile against a fresh stable observation",
                }
            )
            payload.update(
                {
                    "post_observation": "unstable",
                    "reconciliation": "pending",
                    "goal_verification": "unknown",
                    "reconciliation_error": reconciliation_error,
                    "settlement_trace": [
                        {
                            "sample_index": 0,
                            "captured_at_ms": 1_799_999_999_901,
                            "position": {"x": 0, "y": 64, "z": 0},
                            "on_ground": True,
                            "velocity": {"x": 0, "y": 0, "z": 0},
                            "durable_state_hash": "9" * 64,
                            "stable_streak": 1,
                            "rejection_reason": "durable_state_changed",
                        }
                    ],
                }
            )
            payload["content_hash"] = canonical_json_hash(payload)
            return ActionReceipt.model_validate(payload)

    executor = CommandExecutor(
        runtime=PendingReconciliationRuntime(repository),
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
    )

    with pytest.raises(ExecutorError) as caught:
        await executor.execute_step(
            command=await command(repository),
            step=ExecuteStep(
                capability="collect",
                parameters={"count": 1},
                maximum_cost=BudgetUsage(
                    max_actions=1, max_travel_distance=16, max_blocks_changed=4
                ),
            ),
            before=Observation.model_validate(MESSAGES["Observation"]),
            ordinal=1,
            strategy_state_hash="b" * 64,
            account=BudgetAccount(limit=budget()),
        )

    persisted = await repository.get_step("step-1")
    if caught.value.error.code != "POST_ACTION_RECONCILIATION_PENDING":
        pytest.fail(f"{caught.value.error.code}: {caught.value.error.message}")
    assert caught.value.error.outcome_known is False
    assert persisted is not None and persisted.state == "unknown"
    assert persisted.receipt is not None
    assert persisted.receipt["outcome"] == "success"


async def test_reconciliation_waits_for_terminal_receipt_observation_to_settle() -> None:
    repository = InMemoryCommandJournal()

    class SettlingTerminalRuntime(Runtime):
        terminal_receipt: ActionReceipt | None = None
        observations = 0

        async def execute_action(self, request, *, timeout=60.0):
            receipt = await super().execute_action(request, timeout=timeout)
            payload = receipt.model_dump(mode="json", exclude={"content_hash"})
            reconciliation_error = dict(MESSAGES["RuntimeProtocolError"])
            reconciliation_error.update(
                {
                    "code": "POST_ACTION_OBSERVATION_UNSTABLE",
                    "message": "post-action state did not settle",
                    "command_id": request.command_id,
                    "step_id": request.step_id,
                    "correlation_id": request.correlation_id,
                    "outcome_known": False,
                    "world_may_have_changed": True,
                    "operator_action": "reconcile against a fresh stable observation",
                }
            )
            payload.update(
                {
                    "post_observation": "unstable",
                    "reconciliation": "pending",
                    "goal_verification": "unknown",
                    "reconciliation_error": reconciliation_error,
                    "settlement_trace": [
                        {
                            "sample_index": 0,
                            "captured_at_ms": 1_799_999_999_901,
                            "position": {"x": 0, "y": 64, "z": 0},
                            "on_ground": True,
                            "velocity": {"x": 0, "y": 0, "z": 0},
                            "durable_state_hash": "9" * 64,
                            "stable_streak": 1,
                            "rejection_reason": "durable_state_changed",
                        }
                    ],
                }
            )
            payload["content_hash"] = canonical_json_hash(payload)
            self.terminal_receipt = ActionReceipt.model_validate(payload)
            return self.terminal_receipt

        async def inspect_action(self, request):
            assert self.terminal_receipt is not None
            return ActionStatus(
                runtime_instance_id=request.runtime_instance_id,
                correlation_id=request.correlation_id,
                state="terminal",
                receipt=self.terminal_receipt,
                retained_until_ms=2_000_000_100_000,
            )

        async def health(self):
            return RuntimeHealth(
                ready=True,
                busy=False,
                runtime_instance_id=self.manifest.runtime_instance_id,
                last_completed_action_sequence=9,
            )

        async def observe(self, request):
            self.observations += 1
            observation = await super().observe(request)
            payload = observation.model_dump(mode="json", exclude={"content_hash"})
            payload["environment"] = {
                **payload["environment"],
                "on_ground": self.observations > 1,
                "velocity": {
                    "x": 0,
                    "y": 0.25 if self.observations == 1 else -0.0784000015,
                    "z": 0,
                },
            }
            payload["content_hash"] = canonical_json_hash(payload)
            return Observation.model_validate(payload)

    runtime = SettlingTerminalRuntime(repository)
    executor = CommandExecutor(
        runtime=runtime,
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
        reconciliation_grace_seconds=0.1,
        reconciliation_poll_seconds=0.001,
    )
    cmd = await command(repository)

    with pytest.raises(ExecutorError) as caught:
        await executor.execute_step(
            command=cmd,
            step=ExecuteStep(
                capability="collect",
                parameters={"count": 1},
                maximum_cost=BudgetUsage(
                    max_actions=1,
                    max_travel_distance=16,
                    max_blocks_changed=4,
                ),
            ),
            before=Observation.model_validate(MESSAGES["Observation"]),
            ordinal=1,
            strategy_state_hash="b" * 64,
            account=BudgetAccount(limit=budget()),
        )

    recovery = await executor.reconcile_unknown(command=cmd, error=caught.value.error)
    persisted = await repository.get_step("step-1")

    assert recovery.decision is RecoveryDecision.SUCCEEDED_RECONCILED
    assert runtime.observations == 2
    assert persisted is not None and persisted.state == "settled"
    assert persisted.receipt is not None


async def test_reconciliation_preserves_cumulative_budget_from_prior_steps() -> None:
    class CapturingJournal(InMemoryCommandJournal):
        def __init__(self) -> None:
            super().__init__()
            self.settlements: list[tuple[dict | None, dict | None]] = []

        async def settle_step(self, step_id, receipt, **kwargs):
            self.settlements.append((kwargs.get("settled_usage"), kwargs.get("reserved_usage")))
            return await super().settle_step(step_id, receipt, **kwargs)

    repository = CapturingJournal()

    class SecondReceiptPendingRuntime(Runtime):
        terminal_receipt: ActionReceipt | None = None

        async def execute_action(self, request, *, timeout=60.0):
            receipt = await super().execute_action(request, timeout=timeout)
            if len(self.requests) == 1:
                return receipt
            payload = receipt.model_dump(mode="json", exclude={"content_hash"})
            reconciliation_error = dict(MESSAGES["RuntimeProtocolError"])
            reconciliation_error.update(
                {
                    "code": "POST_ACTION_STATE_UNSTABLE",
                    "message": "post-action state did not settle",
                    "command_id": request.command_id,
                    "step_id": request.step_id,
                    "correlation_id": request.correlation_id,
                    "outcome_known": False,
                    "world_may_have_changed": True,
                    "operator_action": "reconcile against a fresh stable observation",
                }
            )
            payload.update(
                {
                    "post_observation": "unstable",
                    "reconciliation": "pending",
                    "goal_verification": "unknown",
                    "reconciliation_error": reconciliation_error,
                    "settlement_trace": [
                        {
                            "sample_index": 0,
                            "captured_at_ms": 1_799_999_999_901,
                            "position": {"x": 0, "y": 64, "z": 0},
                            "on_ground": True,
                            "velocity": {"x": 0, "y": 0, "z": 0},
                            "durable_state_hash": "9" * 64,
                            "stable_streak": 1,
                            "rejection_reason": "durable_state_changed",
                        }
                    ],
                }
            )
            payload["content_hash"] = canonical_json_hash(payload)
            self.terminal_receipt = ActionReceipt.model_validate(payload)
            return self.terminal_receipt

        async def inspect_action(self, request):
            assert self.terminal_receipt is not None
            return ActionStatus(
                runtime_instance_id=request.runtime_instance_id,
                correlation_id=request.correlation_id,
                state="terminal",
                receipt=self.terminal_receipt,
                retained_until_ms=2_000_000_100_000,
            )

        async def health(self):
            return RuntimeHealth(
                ready=True,
                busy=False,
                runtime_instance_id=self.manifest.runtime_instance_id,
                last_completed_action_sequence=9,
            )

    counters: dict[str, int] = {}

    def make_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]}"

    runtime = SecondReceiptPendingRuntime(repository)
    executor = CommandExecutor(
        runtime=runtime,
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=make_id,
    )
    cmd = await command(repository)
    step = ExecuteStep(
        capability="collect",
        parameters={"count": 1},
        maximum_cost=BudgetUsage(
            max_actions=1,
            max_travel_distance=16,
            max_blocks_changed=4,
        ),
    )

    first = await executor.execute_step(
        command=cmd,
        step=step,
        before=Observation.model_validate(MESSAGES["Observation"]),
        ordinal=1,
        strategy_state_hash="b" * 64,
        account=BudgetAccount(limit=budget()),
    )
    with pytest.raises(ExecutorError) as caught:
        await executor.execute_step(
            command=cmd,
            step=step,
            before=first.after,
            ordinal=2,
            strategy_state_hash="c" * 64,
            account=first.account,
            previous_receipt_hash=first.receipt.content_hash,
        )

    if caught.value.error.code != "POST_ACTION_RECONCILIATION_PENDING":
        pytest.fail(f"{caught.value.error.code}: {caught.value.error.message}")
    recovery = await executor.reconcile_unknown(command=cmd, error=caught.value.error)

    assert recovery.decision is RecoveryDecision.SUCCEEDED_RECONCILED
    assert repository.settlements[-1] == (
        {
            "max_actions": 2,
            "max_strategy_attempts": 0,
            "max_travel_distance": 4.0,
            "max_blocks_changed": 2,
            "max_damage_taken": 0.0,
            "resource_consumption": {},
        },
        {
            "max_actions": 0,
            "max_strategy_attempts": 0,
            "max_travel_distance": 0.0,
            "max_blocks_changed": 0,
            "max_damage_taken": 0.0,
            "resource_consumption": {},
        },
    )


async def test_first_step_joins_existing_runtime_receipt_chain_head() -> None:
    repository = InMemoryCommandJournal()

    class GlobalChainRuntime(Runtime):
        async def execute_action(self, request, *, timeout=60.0):
            receipt = await super().execute_action(request, timeout=timeout)
            payload = receipt.model_dump(mode="json", exclude={"content_hash"})
            payload["previous_receipt_hash"] = "f" * 64
            payload["content_hash"] = canonical_json_hash(payload)
            return ActionReceipt.model_validate(payload)

    runtime = GlobalChainRuntime(repository)
    executor = CommandExecutor(
        runtime=runtime,
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
    )

    result = await executor.execute_step(
        command=await command(repository),
        step=ExecuteStep(
            capability="collect",
            parameters={"count": 1},
            maximum_cost=BudgetUsage(
                max_actions=1,
                max_travel_distance=16,
                max_blocks_changed=4,
            ),
        ),
        before=Observation.model_validate(MESSAGES["Observation"]),
        ordinal=1,
        strategy_state_hash="b" * 64,
        account=BudgetAccount(limit=budget()),
        previous_receipt_hash="",
    )

    assert result.receipt.previous_receipt_hash == "f" * 64


def test_reconciled_step_cannot_complete_an_unverified_blueprint_goal() -> None:
    shelter = starter_shelter_blueprint()
    recovery = ReconciliationResult(
        decision=RecoveryDecision.SUCCEEDED_RECONCILED,
        details={},
        receipt=ActionReceipt.model_validate(MESSAGES["ActionReceipt"]),
        observation=Observation.model_validate(MESSAGES["Observation"]),
    )
    command_record = SimpleNamespace(
        mode="mission",
        payload={
            "goal": {
                "intent": "build",
                "target": shelter.blueprint_id,
                "quantity": 1,
                "constraints": {},
                "success_predicates": [
                    {
                        "kind": "structure_matches_blueprint",
                        "blueprint_id": shelter.blueprint_id,
                        "blueprint_hash": shelter.canonical_hash,
                    }
                ],
            }
        },
    )

    terminal = _reconciled_terminal_for_command(
        command=command_record,
        recovery=recovery,
        verifier=GoalVerifier(),
    )

    assert terminal is CommandState.FAILED_RECONCILED


def test_reconciled_combat_receipt_can_verify_the_whole_single_step_goal() -> None:
    payload = dict(MESSAGES["ActionReceipt"])
    payload.update(
        {
            "capability": "attack",
            "outcome": "success",
            "combat": {
                "target_entity_id": "42",
                "target_entity_type": "minecraft:zombie",
                "outcome": "defeated",
                "bot_health_before": 20,
                "bot_health_after": 20,
                "target_health_before": 20,
                "target_health_after": 0,
                "started_tick": 10,
                "finished_tick": 20,
            },
        }
    )
    payload["content_hash"] = canonical_json_hash(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    recovery = ReconciliationResult(
        decision=RecoveryDecision.SUCCEEDED_RECONCILED,
        details={},
        receipt=ActionReceipt.model_validate(payload),
        observation=Observation.model_validate(MESSAGES["Observation"]),
    )
    command_record = SimpleNamespace(
        mode="mission",
        payload={
            "goal": {
                "intent": "combat",
                "target": "minecraft:zombie",
                "quantity": 1,
                "constraints": {},
                "success_predicates": [
                    {
                        "kind": "entity_defeated",
                        "entity": "minecraft:zombie",
                        "quantity": 1,
                    }
                ],
            }
        },
    )

    terminal = _reconciled_terminal_for_command(
        command=command_record,
        recovery=recovery,
        verifier=GoalVerifier(),
    )

    assert terminal is CommandState.SUCCEEDED_RECONCILED


@pytest.mark.parametrize("failure", ["cancelled", "deadline", "unauthorized"])
async def test_executor_rejects_before_runtime_dispatch(failure: str) -> None:
    repository = InMemoryCommandJournal()
    runtime = Runtime(repository)
    executor = CommandExecutor(
        runtime=runtime,
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
    )
    cmd = await command(repository)
    if failure == "cancelled":
        cmd = cmd.model_copy(update={"cancel_requested_at_ms": 10})
    if failure == "deadline":
        cmd = cmd.model_copy(update={"execution_deadline_ms": 10})
    capability = "unknown" if failure == "unauthorized" else "collect"
    step = ExecuteStep(
        capability=capability,
        parameters={"count": 1},
        maximum_cost=BudgetUsage(max_actions=1),
    )

    with pytest.raises(ExecutorError):
        await executor.execute_step(
            command=cmd,
            step=step,
            before=Observation.model_validate(MESSAGES["Observation"]),
            ordinal=1,
            strategy_state_hash="b" * 64,
            account=BudgetAccount(limit=budget()),
        )

    assert runtime.requests == []


async def test_goal_verifier_overrides_strategy_success_claim() -> None:
    class Verifier:
        def verify(self, **_kwargs):
            return {"satisfied": False, "evidence_hashes": []}

    assert (
        CommandExecutor.verify_completion(
            verifier=Verifier(), goal=object(), strategy_complete=True, evidence=[]
        )["satisfied"]
        is False
    )


async def test_executor_reconciles_lost_response_from_persisted_correlation_without_replay() -> (
    None
):
    repository = InMemoryCommandJournal()

    class ResponseLostRuntime(Runtime):
        terminal_receipt: ActionReceipt | None = None

        async def execute_action(self, request, *, timeout=60.0):
            self.terminal_receipt = await super().execute_action(request, timeout=timeout)
            raise ConnectionError("response lost after mutation")

        async def inspect_action(self, request):
            assert self.terminal_receipt is not None
            return ActionStatus(
                runtime_instance_id=request.runtime_instance_id,
                correlation_id=request.correlation_id,
                state="terminal",
                receipt=self.terminal_receipt,
                retained_until_ms=2_000_000_100_000,
            )

        async def health(self):
            return RuntimeHealth(
                ready=True,
                busy=False,
                runtime_instance_id=self.manifest.runtime_instance_id,
                last_completed_action_sequence=9,
            )

    runtime = ResponseLostRuntime(repository)
    executor = CommandExecutor(
        runtime=runtime,
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
    )
    cmd = await command(repository)
    step = ExecuteStep(
        capability="collect",
        parameters={"count": 1},
        maximum_cost=BudgetUsage(max_actions=1, max_travel_distance=16, max_blocks_changed=4),
    )

    with pytest.raises(ExecutorError) as caught:
        await executor.execute_step(
            command=cmd,
            step=step,
            before=Observation.model_validate(MESSAGES["Observation"]),
            ordinal=1,
            strategy_state_hash="b" * 64,
            account=BudgetAccount(limit=budget()),
        )

    recovery = await executor.reconcile_unknown(command=cmd, error=caught.value.error)

    persisted = await repository.get_step("step-1")
    facts = await repository.command_facts(cmd.command_id)
    assert recovery.decision is RecoveryDecision.SUCCEEDED_RECONCILED
    assert persisted is not None and persisted.state == "settled"
    assert len(runtime.requests) == 1
    assert facts["recoveries"] == 1


async def test_executor_blocks_recovery_when_fresh_state_is_not_receipt_explained() -> None:
    repository = InMemoryCommandJournal()

    class UnexplainedDeltaRuntime(Runtime):
        terminal_receipt: ActionReceipt | None = None

        async def execute_action(self, request, *, timeout=60.0):
            self.terminal_receipt = await super().execute_action(request, timeout=timeout)
            raise ConnectionError("response lost after mutation")

        async def inspect_action(self, request):
            assert self.terminal_receipt is not None
            return ActionStatus(
                runtime_instance_id=request.runtime_instance_id,
                correlation_id=request.correlation_id,
                state="terminal",
                receipt=self.terminal_receipt,
                retained_until_ms=2_000_000_100_000,
            )

        async def health(self):
            return RuntimeHealth(
                ready=True,
                busy=False,
                runtime_instance_id=self.manifest.runtime_instance_id,
                last_completed_action_sequence=9,
            )

        async def observe(self, request):
            observation = await super().observe(request)
            payload = observation.model_dump(mode="json", exclude={"content_hash"})
            payload["inventory"] = {"oak_log": 2}
            payload["content_hash"] = canonical_json_hash(payload)
            return Observation.model_validate(payload)

    runtime = UnexplainedDeltaRuntime(repository)
    executor = CommandExecutor(
        runtime=runtime,
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
    )
    cmd = await command(repository)

    with pytest.raises(ExecutorError) as caught:
        await executor.execute_step(
            command=cmd,
            step=ExecuteStep(
                capability="collect",
                parameters={"count": 1},
                maximum_cost=BudgetUsage(
                    max_actions=1, max_travel_distance=16, max_blocks_changed=4
                ),
            ),
            before=Observation.model_validate(MESSAGES["Observation"]),
            ordinal=1,
            strategy_state_hash="b" * 64,
            account=BudgetAccount(limit=budget()),
        )

    recovery = await executor.reconcile_unknown(command=cmd, error=caught.value.error)

    assert recovery.decision is RecoveryDecision.BLOCKED_UNKNOWN
    assert recovery.details["mutations_explained"] is False
    assert recovery.details["rejected_receipt"]["receipt_id"] == runtime.terminal_receipt.receipt_id
    assert recovery.details["fresh_observation"]["inventory"] == {"oak_log": 2}
    assert recovery.details["observable_state_diff"] == {
        "inventory": {
            "receipt_after": {"oak_log": 1},
            "fresh_observation": {"oak_log": 2},
        }
    }


async def test_executor_waits_bounded_grace_for_cancelled_action_receipt() -> None:
    repository = InMemoryCommandJournal()

    class SlowCancelRuntime(Runtime):
        terminal_receipt: ActionReceipt | None = None
        inspections = 0

        async def execute_action(self, request, *, timeout=60.0):
            self.terminal_receipt = await super().execute_action(request, timeout=timeout)
            raise ConnectionError("response lost after mutation")

        async def inspect_action(self, request):
            self.inspections += 1
            if self.inspections == 1:
                return ActionStatus(
                    runtime_instance_id=request.runtime_instance_id,
                    correlation_id=request.correlation_id,
                    state="running",
                )
            assert self.terminal_receipt is not None
            return ActionStatus(
                runtime_instance_id=request.runtime_instance_id,
                correlation_id=request.correlation_id,
                state="terminal",
                receipt=self.terminal_receipt,
                retained_until_ms=2_000_000_100_000,
            )

        async def cancel_action(self, request):
            return CancellationAck(
                runtime_instance_id=request.runtime_instance_id,
                correlation_id=request.correlation_id,
                accepted=True,
                accepted_at_ms=1_800_000_000_000,
            )

        async def health(self):
            return RuntimeHealth(
                ready=True,
                busy=False,
                runtime_instance_id=self.manifest.runtime_instance_id,
                last_completed_action_sequence=9,
            )

    runtime = SlowCancelRuntime(repository)
    executor = CommandExecutor(
        runtime=runtime,
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
        reconciliation_grace_seconds=0.1,
        reconciliation_poll_seconds=0.001,
    )
    cmd = await command(repository)

    with pytest.raises(ExecutorError) as caught:
        await executor.execute_step(
            command=cmd,
            step=ExecuteStep(
                capability="collect",
                parameters={"count": 1},
                maximum_cost=BudgetUsage(
                    max_actions=1, max_travel_distance=16, max_blocks_changed=4
                ),
            ),
            before=Observation.model_validate(MESSAGES["Observation"]),
            ordinal=1,
            strategy_state_hash="b" * 64,
            account=BudgetAccount(limit=budget()),
        )

    recovery = await executor.reconcile_unknown(command=cmd, error=caught.value.error)

    assert recovery.decision is RecoveryDecision.SUCCEEDED_RECONCILED
    assert runtime.inspections == 2


async def test_executor_settles_cancelled_receipt_then_reports_cancelled_command() -> None:
    repository = InMemoryCommandJournal()

    class CancelledRuntime(Runtime):
        async def execute_action(self, request, *, timeout=60.0):
            receipt = await super().execute_action(request, timeout=timeout)
            payload = receipt.model_dump(mode="json", exclude={"content_hash"})
            payload.update({"outcome": "cancelled", "error": None})
            payload["content_hash"] = canonical_json_hash(payload)
            return ActionReceipt.model_validate(payload)

    executor = CommandExecutor(
        runtime=CancelledRuntime(repository),
        repository=repository,
        now_ms=lambda: 1_800_000_000_000,
        make_id=lambda prefix: f"{prefix}-1",
    )
    cmd = await command(repository)

    with pytest.raises(ExecutorError) as caught:
        await executor.execute_step(
            command=cmd,
            step=ExecuteStep(
                capability="collect",
                parameters={"count": 1},
                maximum_cost=BudgetUsage(
                    max_actions=1, max_travel_distance=16, max_blocks_changed=4
                ),
            ),
            before=Observation.model_validate(MESSAGES["Observation"]),
            ordinal=1,
            strategy_state_hash="b" * 64,
            account=BudgetAccount(limit=budget()),
        )

    persisted = await repository.get_step("step-1")
    assert caught.value.error.code == "CANCELLATION_REQUESTED"
    assert persisted is not None and persisted.state == "settled"
