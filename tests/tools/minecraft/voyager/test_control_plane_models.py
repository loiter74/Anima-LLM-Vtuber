"""Goal, budget, and command state contracts for the unified control plane."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from animetta.tools.gamebot.contracts.v2 import BudgetVector
from animetta.tools.minecraft.voyager.budget import (
    BudgetAccount,
    BudgetExceededError,
    BudgetUsage,
    ExecutionBudget,
    RequestedBudget,
    budget_usage_from_vector,
    effective_budget,
)
from animetta.tools.minecraft.voyager.command_models import (
    CallerWaitState,
    CancellationFact,
    CommandProjection,
    CommandState,
    ControllerState,
    ControlPlaneError,
    ExecutionState,
    QueueState,
    validate_transition,
)
from animetta.tools.minecraft.voyager.control_plane import execution_budget_from_json
from animetta.tools.minecraft.voyager.goal_models import (
    AtomicAction,
    ExecutePayload,
    ExecutionMode,
    GoalSpec,
)


def test_goal_spec_is_discriminated_normalized_and_hash_stable() -> None:
    adapter = TypeAdapter(GoalSpec)
    goal = adapter.validate_python(
        {
            "intent": "acquire",
            "target": "oak_log",
            "quantity": 4,
            "success_predicates": [
                {"kind": "inventory_at_least", "item": "oak_log", "quantity": 4}
            ],
        }
    )
    same = adapter.validate_python(
        {
            "success_predicates": [
                {"quantity": 4, "item": "oak_log", "kind": "inventory_at_least"}
            ],
            "quantity": 4,
            "target": "oak_log",
            "intent": "acquire",
        }
    )

    assert goal.canonical_hash == same.canonical_hash
    assert goal.model_copy(update={"quantity": 5}).quantity == 5
    with pytest.raises(ValidationError):
        adapter.validate_python("collect some wood")


@pytest.mark.parametrize("mode", ["learn", "live", "fallback"])
def test_goal_modes_require_goal_and_reject_atomic_action(mode: str) -> None:
    with pytest.raises(ValidationError):
        ExecutePayload(
            mode=mode,
            action=AtomicAction(capability="collect", parameters={"count": 1}),
        )


def test_atomic_mode_requires_exactly_one_atomic_action() -> None:
    payload = ExecutePayload(
        mode=ExecutionMode.ATOMIC,
        action=AtomicAction(capability="collect", parameters={"count": 1}),
    )
    assert payload.action is not None
    with pytest.raises(ValidationError):
        ExecutePayload(mode=ExecutionMode.ATOMIC)


def test_effective_budget_clamps_requested_values_to_mode_maximum() -> None:
    maximum = ExecutionBudget(
        queue_timeout_ms=5_000,
        execution_timeout_ms=30_000,
        max_actions=4,
        max_strategy_attempts=2,
        max_travel_distance=64,
        max_blocks_changed=8,
        max_damage_taken=4,
        protected_items=frozenset({"diamond_pickaxe"}),
        resource_consumption={"oak_log": 8},
    )
    requested = RequestedBudget(max_actions=99, max_travel_distance=12)

    effective = effective_budget(requested, maximum)

    assert effective.max_actions == 4
    assert effective.max_travel_distance == 12
    assert effective.protected_items == frozenset({"diamond_pickaxe"})


def test_strict_execution_budget_restores_frozenset_from_journal_json() -> None:
    serialized = ExecutionBudget(
        queue_timeout_ms=1_000,
        execution_timeout_ms=10_000,
        max_actions=1,
        max_strategy_attempts=1,
        max_travel_distance=64,
        max_blocks_changed=8,
        max_damage_taken=4,
        protected_items=frozenset({"diamond_pickaxe"}),
    ).model_dump(mode="json")

    restored = execution_budget_from_json(serialized)

    assert restored.protected_items == frozenset({"diamond_pickaxe"})


def test_runtime_budget_vector_maps_only_consumable_usage() -> None:
    vector = BudgetVector(
        max_actions=1,
        max_strategy_attempts=1,
        max_travel_distance=3,
        max_blocks_changed=0,
        max_damage_taken=0,
        protected_items=("diamond_pickaxe",),
        resource_consumption={"bread": 1},
    )

    assert budget_usage_from_vector(vector) == BudgetUsage(
        max_actions=1,
        max_strategy_attempts=1,
        max_travel_distance=3,
        max_blocks_changed=0,
        max_damage_taken=0,
        resource_consumption={"bread": 1},
    )


def test_parent_budget_is_shared_across_retry_and_validation_phases() -> None:
    limit = ExecutionBudget(
        queue_timeout_ms=1_000,
        execution_timeout_ms=10_000,
        max_actions=2,
        max_strategy_attempts=2,
        max_travel_distance=10,
        max_blocks_changed=2,
        max_damage_taken=2,
    )
    account = BudgetAccount(limit=limit)
    account = account.charge(BudgetUsage(max_actions=1, max_strategy_attempts=1))
    account = account.charge(BudgetUsage(max_actions=1, max_strategy_attempts=1))

    assert account.remaining.max_actions == 0
    with pytest.raises(BudgetExceededError):
        account.charge(BudgetUsage(max_actions=1))


def test_reservations_are_conservative_and_unused_amount_is_released() -> None:
    limit = ExecutionBudget(
        queue_timeout_ms=1_000,
        execution_timeout_ms=10_000,
        max_actions=3,
        max_strategy_attempts=2,
        max_travel_distance=20,
        max_blocks_changed=5,
        max_damage_taken=3,
    )
    account = BudgetAccount(limit=limit).reserve(
        "step-1", BudgetUsage(max_actions=1, max_blocks_changed=3)
    )
    settled = account.settle("step-1", BudgetUsage(max_actions=1, max_blocks_changed=1))

    assert settled.remaining.max_blocks_changed == 4
    assert "step-1" not in settled.reservations


def test_command_transition_table_rejects_replay_and_terminal_escape() -> None:
    assert validate_transition(CommandState.QUEUED, CommandState.RUNNING)
    assert validate_transition(CommandState.RUNNING, CommandState.RECONCILING)
    assert validate_transition(CommandState.RECONCILING, CommandState.BLOCKED_UNKNOWN)
    with pytest.raises(ValueError):
        validate_transition(CommandState.SUCCEEDED, CommandState.RUNNING)
    with pytest.raises(ValueError):
        validate_transition(CommandState.INTERRUPTED_BEFORE_START, CommandState.QUEUED)


def test_wait_queue_execution_and_controller_lifecycles_are_independent() -> None:
    assert CallerWaitState.TIMED_OUT.value == "timed_out"
    assert QueueState.ELIGIBLE.value == "eligible"
    assert ExecutionState.RECONCILING.value == "reconciling"
    assert ControllerState.QUARANTINED.value == "quarantined"

    error = ControlPlaneError(
        code="RUNTIME_OUTCOME_UNKNOWN",
        message="response lost after mutation",
        phase="recovery",
        outcome_known=False,
        world_may_have_changed=True,
        caller_may_resubmit=False,
        operator_action="inspect the original correlation",
    )
    cancellation = CancellationFact(requested_at_ms=10, reason="operator stop")
    projection = CommandProjection(
        projection_version=3,
        updated_at_ms=20,
        command_id="command-1",
        caller_scope="socket:abc",
        request_id="request-1",
        state=CommandState.RECONCILING,
        caller_wait=CallerWaitState.TIMED_OUT,
        queue=QueueState.DISPATCHED,
        execution=ExecutionState.RECONCILING,
        error=error,
    )

    assert cancellation.signal_accepted is None
    assert projection.error is not None and projection.error.world_may_have_changed
