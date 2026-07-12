"""Single-owner Voyager mode and session lifecycle."""

from __future__ import annotations

import asyncio
import importlib

import pytest

from animetta.tools.gamebot.contracts import (
    CapabilityManifest,
    CapabilityRisk,
    GameBotCapability,
)
from animetta.tools.minecraft.voyager.policy import VoyagerPolicy


def _modules():
    return (
        importlib.import_module("animetta.tools.minecraft.voyager.controller"),
        importlib.import_module("animetta.tools.minecraft.voyager.contracts"),
        importlib.import_module("animetta.tools.minecraft.voyager.repository"),
    )


class FakeRuntime:
    is_running = True

    async def get_capabilities(self):
        return CapabilityManifest(
            protocol_version="1.0",
            runtime_id="runtime-1",
            capabilities=[
                GameBotCapability(
                    name="collect",
                    risk=CapabilityRisk.SURVIVAL_SAFE,
                    parameters={},
                )
            ],
        )


class SessionTracker:
    def __init__(self) -> None:
        self.active = 0
        self.maximum_active = 0
        self.created: list[FakeSession] = []


class FakeSession:
    def __init__(self, context, tracker: SessionTracker) -> None:
        self.context = context
        self.tracker = tracker
        self.started = asyncio.Event()
        self.cancelled = False
        self.goals: list[str] = []

    async def run(self) -> None:
        self.tracker.active += 1
        self.tracker.maximum_active = max(self.tracker.maximum_active, self.tracker.active)
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.tracker.active -= 1

    async def run_goal(self, goal: str):
        self.goals.append(goal)
        return {"outcome": "success", "goal": goal, "session_id": self.context.session_id}


def _controller(*, recovery=None):
    controller_module, contracts_module, repository_module = _modules()
    tracker = SessionTracker()

    def factory(context):
        session = FakeSession(context, tracker)
        tracker.created.append(session)
        return session

    controller = controller_module.VoyagerController(
        runtime=FakeRuntime(),
        policy=VoyagerPolicy(supported_protocol="1.0", allowed_capabilities={"collect"}),
        session_factories={
            contracts_module.VoyagerMode.LEARN: factory,
            contracts_module.VoyagerMode.LIVE: factory,
            contracts_module.VoyagerMode.FALLBACK: factory,
        },
        repository=repository_module.InMemoryVoyagerRepository(),
        recovery=recovery,
    )
    return controller, tracker, contracts_module


async def test_start_learning_is_idempotent_and_starts_exactly_one_session() -> None:
    controller, tracker, contracts = _controller()

    first = await controller.start_learning(goal="iron_pickaxe")
    second = await controller.start_learning(goal="iron_pickaxe")
    await asyncio.sleep(0)

    assert first.mode is contracts.VoyagerMode.LEARN
    assert first.state is contracts.VoyagerSessionState.RUNNING
    assert second.session_id == first.session_id
    assert len(tracker.created) == 1
    assert tracker.created[0].context.goal == "iron_pickaxe"
    await controller.stop()


async def test_mode_transition_cancels_old_session_before_starting_new_one() -> None:
    controller, tracker, contracts = _controller()
    await controller.start_learning()
    await tracker.created[0].started.wait()

    status = await controller.start_live()
    await tracker.created[1].started.wait()

    assert tracker.created[0].cancelled is True
    assert status.mode is contracts.VoyagerMode.LIVE
    assert tracker.maximum_active == 1
    await controller.stop()


async def test_concurrent_transitions_leave_one_active_session() -> None:
    controller, tracker, contracts = _controller()

    await asyncio.gather(controller.start_learning(), controller.start_live())
    await asyncio.sleep(0)
    status = await controller.status()

    assert status.mode in {contracts.VoyagerMode.LEARN, contracts.VoyagerMode.LIVE}
    assert status.state is contracts.VoyagerSessionState.RUNNING
    assert tracker.active == 1
    assert tracker.maximum_active == 1
    assert sum(not session.cancelled for session in tracker.created) == 1
    await controller.stop()


async def test_stop_is_idempotent_and_returns_structured_status() -> None:
    controller, tracker, contracts = _controller()
    await controller.start_fallback()
    await tracker.created[0].started.wait()

    first = await controller.stop()
    second = await controller.stop()

    assert first.mode is contracts.VoyagerMode.STOPPED
    assert first.state is contracts.VoyagerSessionState.STOPPED
    assert first.session_id == ""
    assert second == first
    assert tracker.active == 0


async def test_live_goal_requires_live_mode_and_uses_active_live_session() -> None:
    controller, tracker, _ = _controller()

    with pytest.raises(RuntimeError, match="live mode"):
        await controller.run_live_goal("collect wood")

    await controller.start_live()
    await tracker.created[0].started.wait()
    result = await controller.run_live_goal("collect wood")

    assert result["outcome"] == "success"
    assert tracker.created[0].goals == ["collect wood"]
    await controller.stop()


async def test_status_exposes_mode_session_goal_and_runtime_identity() -> None:
    controller, _, contracts = _controller()

    started = await controller.start_learning(goal="iron_pickaxe")
    status = await controller.status()

    assert status == started
    assert status.mode is contracts.VoyagerMode.LEARN
    assert status.current_task == "iron_pickaxe"
    assert status.runtime_id == "runtime-1"
    assert status.last_failure is None
    await controller.stop()


async def test_manifest_policy_failure_prevents_session_start() -> None:
    controller_module, contracts, repository = _modules()

    class UnsafeRuntime(FakeRuntime):
        async def get_capabilities(self):
            return CapabilityManifest(
                protocol_version="1.0",
                runtime_id="runtime-unsafe",
                capabilities=[
                    GameBotCapability(
                        name="fly",
                        risk=CapabilityRisk.SURVIVAL_SAFE,
                        parameters={},
                    )
                ],
            )

    controller = controller_module.VoyagerController(
        runtime=UnsafeRuntime(),
        policy=VoyagerPolicy(supported_protocol="1.0", allowed_capabilities={"collect"}),
        session_factories={},
        repository=repository.InMemoryVoyagerRepository(),
    )

    with pytest.raises(RuntimeError, match="UNKNOWN_CAPABILITY"):
        await controller.start_learning()

    status = await controller.status()
    assert status.mode is contracts.VoyagerMode.STOPPED
    assert status.state is contracts.VoyagerSessionState.STOPPED


async def test_clean_recovery_restarts_previous_mode_with_new_session_id() -> None:
    recovery_module = importlib.import_module("animetta.tools.minecraft.voyager.recovery")
    calls = []

    class CleanRecovery:
        async def recover(self, **kwargs):
            calls.append(kwargs)
            return recovery_module.RecoveryResult(state=recovery_module.RecoveryState.RESUMED)

    controller, tracker, contracts = _controller(recovery=CleanRecovery())
    started = await controller.start_learning(goal="iron_pickaxe")
    await tracker.created[0].started.wait()

    recovered = await controller.recover(
        interrupted_task_id="task-interrupted",
        active_correlation_id="corr-active",
        partial_receipts=[],
    )
    await tracker.created[1].started.wait()

    assert tracker.created[0].cancelled is True
    assert recovered.mode is contracts.VoyagerMode.LEARN
    assert recovered.state is contracts.VoyagerSessionState.RUNNING
    assert recovered.session_id != started.session_id
    assert recovered.current_task == "iron_pickaxe"
    assert calls[0]["session_id"] == started.session_id
    assert tracker.maximum_active == 1
    await controller.stop()


async def test_quarantined_recovery_leaves_no_active_session() -> None:
    recovery_module = importlib.import_module("animetta.tools.minecraft.voyager.recovery")

    class QuarantinedRecovery:
        async def recover(self, **kwargs):
            return recovery_module.RecoveryResult(
                state=recovery_module.RecoveryState.QUARANTINED,
                reason="unexplained_inventory_delta",
                unexplained_inventory={"iron_pickaxe": 1},
            )

    controller, tracker, contracts = _controller(recovery=QuarantinedRecovery())
    await controller.start_live()
    await tracker.created[0].started.wait()

    status = await controller.recover(
        interrupted_task_id="task-interrupted",
        active_correlation_id="corr-active",
        partial_receipts=[],
    )

    assert status.mode is contracts.VoyagerMode.RECOVERING
    assert status.state is contracts.VoyagerSessionState.QUARANTINED
    assert status.last_failure == "unexplained_inventory_delta"
    assert tracker.active == 0
