"""Startup and shutdown assemble exactly one durable v2 ownership chain."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from animetta.tools.minecraft.core.assembly import (
    _budget_policy,
    _learning_frontier,
    _learning_proposal,
    assemble_control_plane,
)
from animetta.tools.minecraft.core.config import MinecraftConfig
from animetta.tools.minecraft.survival.workflows import diamond_survival_workflow
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.gateway import ExecuteAtomicRequest, ExecuteMissionRequest
from animetta.tools.minecraft.voyager.goal_models import AtomicAction, GoalSpec
from animetta.tools.minecraft.voyager.journal import CommandDraft, JournalCommand, StepRecord
from tests.tools.minecraft.mission.test_coordinator import _fixed_mission

ROOT = Path(__file__).resolve().parents[4]
MESSAGES = json.loads(
    (ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8")
)["messages"]
MANIFEST = MESSAGES["RuntimeManifest"]


class ManifestBridge:
    is_running = True

    def __init__(self, config: MinecraftConfig) -> None:
        self.config = config
        self.calls: list[str] = []

    async def send_command(self, action, params, timeout=60.0):
        del params, timeout
        self.calls.append(action)
        if action == "gamebot_v2_manifest":
            return {"status": "success", "result": MANIFEST}
        raise AssertionError(f"unexpected assembly command: {action}")


async def test_assembly_validates_manifest_starts_one_worker_and_closes_it(
    tmp_path,
) -> None:
    config = MinecraftConfig(
        enabled=True,
        journal_path=str(tmp_path / "commands.db"),
        skill_path=str(tmp_path / "skills.db"),
    )
    bridge = ManifestBridge(config)
    plane = await assemble_control_plane(bridge, config)
    worker = plane.scheduler._worker
    await plane.close()

    assert bridge.calls == ["gamebot_v2_manifest"]
    assert worker is not None
    assert worker.done()
    assert plane.scheduler._worker is None


async def test_assembly_wires_presentation_to_durable_activity_and_emit(tmp_path) -> None:
    config = MinecraftConfig.model_validate(
        {
            "enabled": True,
            "journal_path": str(tmp_path / "commands.db"),
            "skill_path": str(tmp_path / "skills.db"),
            "presentation": {"mode": "visual_only"},
        }
    )
    emitted: list[dict[str, object]] = []

    async def emit(event: dict[str, object]) -> None:
        emitted.append(event)

    plane = await assemble_control_plane(ManifestBridge(config), config, event_emit=emit)
    await plane.scheduler.stop()
    try:
        atomic = await plane.gateway.execute(
            caller_scope="conversation:viewer",
            request=ExecuteAtomicRequest(
                request_id="public-activity-request",
                action=AtomicAction(capability="collect", parameters={"count": 1}),
            ),
        )
        current = await plane.repository.get_command(atomic.command_id)
        assert current is not None
        running_atomic = await plane.repository.transition(
            atomic.command_id,
            expected_version=current.state_version,
            target=CommandState.RUNNING,
            reason_code="DISPATCHED",
            actor="test",
            occurred_at_ms=current.accepted_at_ms + 1,
        )
        await plane.gateway._notify(atomic.command_id)
        await plane.repository.transition(
            atomic.command_id,
            expected_version=running_atomic.state_version,
            target=CommandState.SUCCEEDED,
            reason_code="RECEIPT_ONLY",
            actor="test",
            occurred_at_ms=current.accepted_at_ms + 2,
        )
        await plane.gateway._notify(atomic.command_id)

        goal_command = (
            await plane.repository.create_command(
                CommandDraft(
                    command_id="verified-goal-command",
                    caller_scope="conversation:viewer",
                    request_id="verified-goal-request",
                    request_hash="d" * 64,
                    kind="execute",
                    mode="mission",
                    payload={
                        "mission_id": "public-goal-mission",
                        "goal": {"intent": "acquire", "target": "minecraft:oak_log"},
                    },
                    requested_budget={},
                    effective_budget={},
                    accepted_at_ms=100,
                )
            )
        )[0]
        await plane.gateway._notify(goal_command.command_id)
        for target in (
            CommandState.RUNNING,
            CommandState.BLOCKED_UNKNOWN,
            CommandState.RECONCILING,
            CommandState.SUCCEEDED_RECONCILED,
        ):
            current = await plane.repository.get_command(goal_command.command_id)
            assert current is not None
            await plane.repository.transition(
                goal_command.command_id,
                expected_version=current.state_version,
                target=target,
                reason_code="TEST_TRANSITION",
                actor="test",
                occurred_at_ms=current.accepted_at_ms + current.state_version + 1,
            )
            await plane.gateway._notify(goal_command.command_id)
        page = await plane.gateway.replay_public_activities()
    finally:
        await plane.close()

    activity_events = [
        event for event in emitted if event.get("event") == "minecraft.activity.projection"
    ]
    assert plane.activity_recorder.enabled is True
    assert [event.payload.phase for event in page.events] == [
        "planning",
        "finished",
        "finished",
    ]
    assert [event.payload.outcome for event in page.events] == [
        "active",
        "blocked",
        "succeeded",
    ]
    assert page.events[0].payload.intent == "acquire"
    assert activity_events == [event.model_dump(mode="json") for event in page.events]


async def test_presentation_force_off_disables_journal_emit_and_replay(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MC_MCP_PRESENTATION_FORCE_OFF", "true")
    config = MinecraftConfig.model_validate(
        {
            "enabled": True,
            "journal_path": str(tmp_path / "commands.db"),
            "skill_path": str(tmp_path / "skills.db"),
            "presentation": {"mode": "full"},
        }
    )
    emitted: list[dict[str, object]] = []

    async def emit(event: dict[str, object]) -> None:
        emitted.append(event)

    plane = await assemble_control_plane(ManifestBridge(config), config, event_emit=emit)
    await plane.scheduler.stop()
    try:
        command = (
            await plane.repository.create_command(
                CommandDraft(
                    command_id="force-off-command",
                    caller_scope="conversation:viewer",
                    request_id="force-off-request",
                    request_hash="e" * 64,
                    kind="execute",
                    mode="mission",
                    payload={"goal": {"intent": "build", "target": "minecraft:shelter"}},
                    requested_budget={},
                    effective_budget={},
                    accepted_at_ms=100,
                )
            )
        )[0]
        await plane.gateway._notify(command.command_id)
        raw_page = await plane.repository.read_recent_activity()
        public_page = await plane.gateway.replay_public_activities()
    finally:
        await plane.close()

    assert plane.activity_recorder.enabled is False
    assert raw_page.records == ()
    assert public_page.events == ()
    assert not any(event.get("event") == "minecraft.activity.projection" for event in emitted)


async def test_runtime_profile_off_disables_python_activity_projection(tmp_path) -> None:
    config = MinecraftConfig.model_validate(
        {
            "enabled": True,
            "journal_path": str(tmp_path / "commands.db"),
            "skill_path": str(tmp_path / "skills.db"),
            "presentation": {"mode": "full"},
        }
    )
    bridge = ManifestBridge(config)
    bridge.active_presentation_mode = "off"

    plane = await assemble_control_plane(bridge, config)
    await plane.close()

    assert plane.activity_recorder.enabled is False


async def test_atomic_completion_does_not_commit_goal_evidence(tmp_path) -> None:
    config = MinecraftConfig(
        enabled=True,
        journal_path=str(tmp_path / "commands.db"),
        skill_path=str(tmp_path / "skills.db"),
    )
    bridge = ManifestBridge(config)
    plane = await assemble_control_plane(bridge, config)
    command = JournalCommand(
        command_id="atomic-status-command",
        caller_scope="probe:test",
        request_id="atomic-status-request",
        request_hash="a" * 64,
        kind="execute",
        mode="atomic",
        payload={"action": {"capability": "status", "parameters": {}}},
        requested_budget={},
        effective_budget={},
        accepted_at_ms=1,
        queue_sequence=1,
        state=CommandState.RUNNING,
        state_version=1,
    )

    try:
        callback = plane.controller._on_strategy_complete
        assert callback is not None
        await callback(
            command=command,
            manifest=await plane.adapter.get_manifest(),
            output={"selected_strategy": "atomic"},
        )
    finally:
        await plane.close()


async def test_mission_factory_restores_strict_budget_from_journal_json(tmp_path) -> None:
    config = MinecraftConfig(
        enabled=True,
        journal_path=str(tmp_path / "commands.db"),
        skill_path=str(tmp_path / "skills.db"),
    )
    bridge = ManifestBridge(config)
    plane = await assemble_control_plane(bridge, config)
    budget = _budget_policy(config).learn
    command = JournalCommand(
        command_id="mission-showcase-defeat-zombie-v1",
        caller_scope="showcase:test",
        request_id="showcase:defeat-zombie:v1",
        request_hash="a" * 64,
        kind="execute",
        mode="mission",
        payload={
            "goal": {
                "intent": "combat",
                "target": "defeat a zombie",
                "success_predicates": [
                    {
                        "kind": "entity_defeated",
                        "entity": "minecraft:zombie",
                        "quantity": 1,
                    }
                ],
            },
            "execution_policy": {"allow_skill_learning": True},
        },
        requested_budget=budget.model_dump(mode="json"),
        effective_budget=budget.model_dump(mode="json"),
        accepted_at_ms=1,
        queue_deadline_ms=2,
        execution_deadline_ms=3,
        queue_sequence=1,
        state=CommandState.RUNNING,
        state_version=1,
        started_at_ms=2,
    )

    try:
        manifest = await plane.adapter.get_manifest()
        strategy = plane.controller._strategy_factories["mission"](
            manifest,
            command,
        )
    finally:
        await plane.close()

    learn = strategy._strategies["learn"]
    assert learn._compilation_budget.protected_items == frozenset(
        {"diamond_pickaxe", "netherite_pickaxe"}
    )


async def test_failed_mission_receipt_with_protected_items_is_settled(tmp_path) -> None:
    config = MinecraftConfig(
        enabled=True,
        journal_path=str(tmp_path / "commands.db"),
        skill_path=str(tmp_path / "skills.db"),
    )
    bridge = ManifestBridge(config)
    plane = await assemble_control_plane(bridge, config)
    await plane.scheduler.stop()
    mission = _fixed_mission()
    handle = await plane.gateway.execute(
        caller_scope="showcase:test",
        request=ExecuteMissionRequest(
            contract_version="2",
            kind="mission",
            request_id="showcase-mission-request",
            mission=mission,
        ),
    )
    command_id = handle.eligible_command_id
    assert command_id is not None
    queued = await plane.repository.get_command(command_id)
    assert queued is not None
    step = StepRecord(
        step_id="step-final2",
        command_id=command_id,
        ordinal=1,
        strategy_state_hash="a" * 64,
        capability="goto",
        params_hash="b" * 64,
        params={"x": 1, "y": 2, "z": 3},
        correlation_id="correlation-final2",
        runtime_instance_id="runtime-final2",
        state="reserved",
        reservation=BudgetUsage(max_actions=1).model_dump(mode="json"),
        before_observation_hash="c" * 64,
    )
    await plane.repository.reserve_step(step)
    receipt = json.loads(json.dumps(MESSAGES["ActionReceipt"]))
    receipt.update(
        {
            "receipt_id": "receipt-final2",
            "command_id": command_id,
            "step_id": step.step_id,
            "correlation_id": step.correlation_id,
            "runtime_instance_id": step.runtime_instance_id,
        }
    )
    receipt["budget_usage"] = {
        "max_actions": 0,
        "max_strategy_attempts": 0,
        "max_travel_distance": 0,
        "max_blocks_changed": 0,
        "max_damage_taken": 0,
        "protected_items": ["diamond_pickaxe"],
        "resource_consumption": {},
    }
    await plane.repository.settle_step(step.step_id, receipt)
    running = await plane.repository.transition(
        command_id,
        expected_version=queued.state_version,
        target=CommandState.RUNNING,
        reason_code="DISPATCHED",
        actor="worker",
        occurred_at_ms=10,
    )
    await plane.repository.transition(
        command_id,
        expected_version=running.state_version,
        target=CommandState.FAILED,
        reason_code="ACTION_FAILED",
        actor="controller",
        occurred_at_ms=11,
    )

    try:
        notify = plane.scheduler._on_command_changed
        assert notify is not None
        await notify(command_id)
        snapshot = await plane.mission_repository.snapshot(mission.mission_id)
    finally:
        await plane.close()

    assert snapshot.mission.status == "failed"
    assert snapshot.objectives[0].status == "failed"


def test_fallback_budget_covers_bounded_diamond_progression() -> None:
    fallback = _budget_policy(MinecraftConfig()).fallback
    reserved = BudgetUsage()
    for step in diamond_survival_workflow().steps:
        reserved = reserved.plus(step.maximum_cost)

    assert fallback.execution_timeout_ms == 45 * 60_000
    assert fallback.max_blocks_changed == 512
    assert reserved.max_actions <= fallback.max_actions
    assert reserved.max_travel_distance <= fallback.max_travel_distance
    assert reserved.max_blocks_changed <= fallback.max_blocks_changed


def test_learning_frontier_supports_a_discovered_resource_acquisition_goal() -> None:
    goal = TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "acquire",
            "target": "raw_copper",
            "constraints": {"source_block": "copper_ore"},
            "success_predicates": [
                {
                    "kind": "inventory_at_least",
                    "item": "raw_copper",
                    "quantity": 1,
                }
            ],
        }
    )

    frontier = _learning_frontier(goal)
    proposal = _learning_proposal(frontier[0])

    assert frontier == ("acquire:raw_copper:copper_ore",)
    assert proposal["capability"] == "collect"
    assert proposal["parameters"] == {"block_type": "copper_ore", "count": 1}


def test_learning_frontier_reaches_diamond_with_typed_collection() -> None:
    goal = TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "acquire",
            "target": "diamond",
            "success_predicates": [
                {
                    "kind": "inventory_at_least",
                    "item": "diamond",
                    "quantity": 1,
                }
            ],
        }
    )

    frontier = _learning_frontier(goal)
    proposal = _learning_proposal(frontier[-1])

    assert frontier[-1] == "diamond"
    assert proposal["capability"] == "collect"
    assert proposal["parameters"] == {"block_type": "diamond_ore", "count": 1}
