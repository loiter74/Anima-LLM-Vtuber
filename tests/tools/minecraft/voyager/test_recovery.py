"""Recovery resumes only from committed, inventory-consistent checkpoints."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

from animetta.tools.gamebot.contracts import (
    ActionOutcome,
    ActionReceipt,
    GameBotObservation,
)
from animetta.tools.minecraft.voyager.contracts import VoyagerCheckpoint
from animetta.tools.minecraft.voyager.repository import InMemoryVoyagerRepository


def _recovery():
    return importlib.import_module("animetta.tools.minecraft.voyager.recovery")


def _observation(observation_id: str, inventory: dict[str, int]):
    return GameBotObservation(
        observation_id=observation_id,
        correlation_id=f"corr-{observation_id}",
        runtime_id="runtime-1",
        captured_at=datetime(2026, 7, 12, tzinfo=UTC),
        inventory=inventory,
    )


def _partial_receipt():
    started = datetime(2026, 7, 12, tzinfo=UTC)
    return ActionReceipt(
        receipt_id="partial-receipt",
        session_id="session-1",
        task_id="interrupted-task",
        correlation_id="active-correlation",
        runtime_id="runtime-1",
        capability="collect",
        params={},
        started_at=started,
        finished_at=started + timedelta(seconds=1),
        before_observation_hash="before",
        after_observation_hash="partial-after",
        outcome=ActionOutcome.CANCELLED,
    )


class FakeRecoveryRuntime:
    is_running = True

    def __init__(self, fresh: GameBotObservation, *, healthy: bool = True) -> None:
        self.fresh = fresh
        self.healthy = healthy
        self.cancelled = []
        self.observed = []

    async def cancel_action(self, correlation_id: str):
        self.cancelled.append(correlation_id)
        return {"cancelled": True}

    async def health(self):
        return {"healthy": self.healthy, "runtime_id": "runtime-1"}

    async def observe(self, correlation_id: str):
        self.observed.append(correlation_id)
        return self.fresh


async def _repository(inventory: dict[str, int]):
    repository = InMemoryVoyagerRepository()
    await repository.commit_checkpoint(
        VoyagerCheckpoint(
            session_id="session-1",
            task_id="committed-task",
            observation_hash="committed-observation",
            unlocked_tech=frozenset({"wood_collection"}),
            metadata={"inventory": inventory},
        )
    )
    return repository


async def test_recovery_cancels_action_invalidates_partial_receipts_and_restores_checkpoint() -> (
    None
):
    recovery = _recovery()
    repository = await _repository({"oak_log": 1})
    runtime = FakeRecoveryRuntime(_observation("fresh", {"oak_log": 1}))
    coordinator = recovery.RecoveryCoordinator(runtime=runtime, repository=repository)
    partial = _partial_receipt()

    result = await coordinator.recover(
        session_id="session-1",
        interrupted_task_id="interrupted-task",
        active_correlation_id="active-correlation",
        partial_receipts=[partial],
    )

    assert result.state is recovery.RecoveryState.RESUMED
    assert runtime.cancelled == ["active-correlation"]
    assert result.checkpoint.task_id == "committed-task"
    assert result.invalid_receipt_hashes == (partial.content_hash,)
    assert result.fresh_observation.observation_id == "fresh"


async def test_recovery_quarantines_unexplained_positive_inventory_delta() -> None:
    recovery = _recovery()
    repository = await _repository({"oak_log": 1})
    runtime = FakeRecoveryRuntime(_observation("fresh", {"oak_log": 1, "iron_pickaxe": 1}))
    coordinator = recovery.RecoveryCoordinator(runtime=runtime, repository=repository)

    result = await coordinator.recover(
        session_id="session-1",
        interrupted_task_id="interrupted-task",
        active_correlation_id="active-correlation",
        partial_receipts=[],
    )

    assert result.state is recovery.RecoveryState.QUARANTINED
    assert result.reason == "unexplained_inventory_delta"
    assert result.unexplained_inventory == {"iron_pickaxe": 1}


async def test_recovery_without_committed_checkpoint_is_quarantined() -> None:
    recovery = _recovery()
    coordinator = recovery.RecoveryCoordinator(
        runtime=FakeRecoveryRuntime(_observation("fresh", {})),
        repository=InMemoryVoyagerRepository(),
    )

    result = await coordinator.recover(
        session_id="session-1",
        interrupted_task_id="interrupted-task",
        active_correlation_id="active-correlation",
        partial_receipts=[],
    )

    assert result.state is recovery.RecoveryState.QUARANTINED
    assert result.reason == "missing_committed_checkpoint"


async def test_recovery_requires_healthy_runtime_before_fresh_observation() -> None:
    recovery = _recovery()
    repository = await _repository({})
    runtime = FakeRecoveryRuntime(_observation("fresh", {}), healthy=False)
    coordinator = recovery.RecoveryCoordinator(runtime=runtime, repository=repository)

    result = await coordinator.recover(
        session_id="session-1",
        interrupted_task_id="interrupted-task",
        active_correlation_id="active-correlation",
        partial_receipts=[],
    )

    assert result.state is recovery.RecoveryState.QUARANTINED
    assert result.reason == "runtime_unhealthy"
    assert runtime.observed == []


async def test_fallback_inventory_cannot_validate_interrupted_learning_task() -> None:
    live = importlib.import_module("animetta.tools.minecraft.voyager.live")
    tech = importlib.import_module("animetta.tools.minecraft.voyager.tech_graph")
    from animetta.tools.gamebot.contracts import CapabilityManifest
    from animetta.tools.minecraft.voyager.contracts import VoyagerMode, VoyagerSessionContext

    async def survival_runner(goal: str, *, task_id: str):
        return {"completed": True, "receipt_hashes": ["fallback-only-receipt"]}

    fallback = live.FallbackSession(
        context=VoyagerSessionContext(
            session_id="fallback-session",
            mode=VoyagerMode.FALLBACK,
            runtime=FakeRecoveryRuntime(_observation("unused", {})),
            manifest=CapabilityManifest(protocol_version="1.0", runtime_id="runtime-1"),
            authorized_capabilities=frozenset(),
            repository=InMemoryVoyagerRepository(),
        ),
        runner=survival_runner,
    )
    fallback_result = await fallback.run_goal(
        "collect wood",
        reason="interrupted learning task",
        parent_task_id="learning-task",
    )
    before = _observation("before", {})
    after = _observation("after", {"oak_log": 64})

    evidence = tech.TechEvidenceVerifier(tech.build_survival_tech_graph()).verify(
        node_id="wood_collection",
        progress=tech.TechProgress(),
        receipts=[],
        before=before,
        after=after,
        session_id="learning-session",
        task_id="learning-task",
        runtime_id="runtime-1",
    )

    assert fallback_result["evidence_eligible"] is False
    assert "receipt_hashes" not in fallback_result
    assert evidence.valid is False
    assert evidence.unlock_record is None
    assert {failure.code for failure in evidence.failures} >= {
        "EMPTY_RECEIPT_CHAIN",
        "UNEXPLAINED_INVENTORY_DELTA",
    }
