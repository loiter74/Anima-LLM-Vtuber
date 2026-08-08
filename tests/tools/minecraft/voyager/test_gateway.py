"""Typed public gateway admission, idempotency, waiting, status, and stop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from animetta.tools.gamebot.contracts.v2 import RuntimeManifest
from animetta.tools.minecraft.mission.coordinator import MissionCoordinator
from animetta.tools.minecraft.mission.projection import MissionProjectionService
from animetta.tools.minecraft.mission.repository import InMemoryMissionRepository
from animetta.tools.minecraft.showcase.micro_gates import build_construction_mission
from animetta.tools.minecraft.voyager.budget import ExecutionBudget, ModeBudgetPolicy
from animetta.tools.minecraft.voyager.gateway import (
    EXECUTE_REQUEST_ADAPTER,
    ExecuteAtomicRequest,
    ExecuteMissionRequest,
    MissionHandle,
    VoyagerGateway,
)
from animetta.tools.minecraft.voyager.journal import InMemoryCommandJournal
from animetta.tools.minecraft.voyager.stop import GlobalStopBarrier
from tests.tools.minecraft.mission.test_coordinator import _fixed_mission

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = RuntimeManifest.model_validate(
    json.loads((ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8"))[
        "messages"
    ]["RuntimeManifest"]
)


def limits() -> ModeBudgetPolicy:
    atomic = ExecutionBudget(
        queue_timeout_ms=1_000,
        execution_timeout_ms=10_000,
        max_actions=4,
        max_strategy_attempts=2,
        max_travel_distance=64,
        max_blocks_changed=8,
        max_damage_taken=4,
    )
    mission = ExecutionBudget(
        queue_timeout_ms=5_000,
        execution_timeout_ms=300_000,
        max_actions=20,
        max_strategy_attempts=12,
        max_travel_distance=256,
        max_blocks_changed=128,
        max_damage_taken=10,
        protected_items=frozenset({"minecraft:diamond_pickaxe"}),
        resource_consumption={"minecraft:oak_planks": 64},
    )
    return ModeBudgetPolicy(learn=mission, live=mission, fallback=mission, atomic=atomic)


def atomic_request(*, wait_seconds: float = 0, max_actions: int = 99) -> ExecuteAtomicRequest:
    return ExecuteAtomicRequest.model_validate(
        {
            "contract_version": "2",
            "kind": "atomic",
            "request_id": "request-1",
            "action": {"capability": "collect", "parameters": {"count": 1}},
            "requested_budget": {"max_actions": max_actions},
            "wait_seconds": wait_seconds,
        }
    )


def gateway(repository: InMemoryCommandJournal) -> VoyagerGateway:
    stop = GlobalStopBarrier(
        repository=repository,
        signal_active=lambda _command_id: _noop(),
        now_ms=lambda: 100,
    )
    return VoyagerGateway(
        repository=repository,
        stop_barrier=stop,
        manifest=MANIFEST,
        budget_policy=limits(),
        now_ms=lambda: 100,
        make_id=lambda prefix: f"{prefix}-1",
        max_wait_seconds=1,
    )


async def _noop() -> None:
    return None


async def test_execute_injects_scope_clamps_budget_and_accepts_asynchronously() -> None:
    repository = InMemoryCommandJournal()
    service = gateway(repository)

    handle = await service.execute(caller_scope="principal:a", request=atomic_request())

    command = await repository.get_command(handle.command_id)
    assert command is not None and command.caller_scope == "principal:a"
    assert command.effective_budget["max_actions"] == 4
    assert handle.state == "queued"
    assert handle.idempotency_reused is False


async def test_wait_metadata_is_excluded_from_idempotency_hash() -> None:
    repository = InMemoryCommandJournal()
    service = gateway(repository)

    first = await service.execute(caller_scope="principal:a", request=atomic_request())
    resumed = await service.execute(
        caller_scope="principal:a", request=atomic_request(wait_seconds=0.01)
    )

    assert resumed.command_id == first.command_id
    assert resumed.idempotency_reused is True


def test_gateway_rejects_natural_language_goal_unknown_capability_and_caller_scope_input() -> None:
    with pytest.raises(ValidationError):
        EXECUTE_REQUEST_ADAPTER.validate_python(
            {"contract_version": "1", "request_id": "x", "mode": "live", "goal": "collect wood"}
        )
    with pytest.raises(ValidationError):
        EXECUTE_REQUEST_ADAPTER.validate_python(
            {
                "contract_version": "2",
                "kind": "atomic",
                "request_id": "x",
                "action": {"capability": "collect", "parameters": {"count": 1}},
                "caller_scope": "forged",
            }
        )


async def test_mission_submission_returns_durable_handle_and_first_leaf() -> None:
    command_repository = InMemoryCommandJournal()
    mission_repository = InMemoryMissionRepository()
    coordinator = MissionCoordinator(
        repository=mission_repository,
        journal=command_repository,
    )
    projection = MissionProjectionService(
        repository=mission_repository,
        journal=command_repository,
    )
    service = gateway(command_repository)
    service.bind_missions(coordinator=coordinator, projection=projection)
    mission = _fixed_mission()
    request = ExecuteMissionRequest(
        contract_version="2",
        kind="mission",
        request_id="mission-request-1",
        mission=mission,
    )

    handle = await service.execute(caller_scope="principal:a", request=request)

    assert isinstance(handle, MissionHandle)
    assert handle.mission_id == mission.mission_id
    assert handle.state == "running"
    assert handle.eligible_objective_id == "fight-zombie"
    assert handle.eligible_command_id is not None
    rehydrated = await service.status_missions(caller_scope="principal:a")
    assert [item.mission_id for item in rehydrated.missions] == [mission.mission_id]


async def test_mission_resource_ceiling_still_applies_when_mode_declares_the_item() -> None:
    command_repository = InMemoryCommandJournal()
    mission_repository = InMemoryMissionRepository()
    coordinator = MissionCoordinator(
        repository=mission_repository,
        journal=command_repository,
    )
    projection = MissionProjectionService(
        repository=mission_repository,
        journal=command_repository,
    )
    service = gateway(command_repository)
    service.bind_missions(coordinator=coordinator, projection=projection)
    mission = build_construction_mission(mission_id="resource-ceiling")

    with pytest.raises(ValidationError, match="child budgets exceed parent mission budget"):
        await service.execute(
            caller_scope="principal:a",
            request=ExecuteMissionRequest(
                request_id="resource-ceiling-request",
                mission=mission,
            ),
        )


async def test_status_is_scope_isolated_projection_read_without_runtime() -> None:
    repository = InMemoryCommandJournal()
    service = gateway(repository)
    await service.execute(caller_scope="principal:a", request=atomic_request())

    own = await service.status(caller_scope="principal:a", limit=10)
    other = await service.status(caller_scope="principal:b", limit=10)

    assert len(own.commands) == 1
    assert other.commands == ()


async def test_stop_delegates_to_durable_global_barrier() -> None:
    repository = InMemoryCommandJournal()
    service = gateway(repository)
    await service.execute(caller_scope="principal:a", request=atomic_request())

    result = await service.stop(caller_scope="principal:a", request_id="stop-1", reason="operator")

    assert result.cancelled_command_ids == ("command-1",)


async def test_quarantine_blocks_execution_but_status_and_stop_remain_available() -> None:
    repository = InMemoryCommandJournal()
    admitted = False
    service = VoyagerGateway(
        repository=repository,
        stop_barrier=GlobalStopBarrier(
            repository=repository,
            signal_active=lambda _command_id: _noop(),
            now_ms=lambda: 100,
        ),
        manifest=MANIFEST,
        budget_policy=limits(),
        now_ms=lambda: 100,
        make_id=lambda prefix: f"{prefix}-1",
        execution_admitted=lambda: admitted,
    )

    with pytest.raises(RuntimeError, match="CONTROLLER_QUARANTINED"):
        await service.execute(caller_scope="principal:a", request=atomic_request())

    assert (await service.status(caller_scope="principal:a")).commands == ()
    stop = await service.stop(
        caller_scope="principal:a", request_id="stop-quarantine", reason="reconcile"
    )
    assert stop.stop_command_id.startswith("stop-")
