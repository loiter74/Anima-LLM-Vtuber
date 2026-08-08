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
from animetta.tools.minecraft.voyager.budget import BudgetUsage
from animetta.tools.minecraft.voyager.command_models import CommandState
from animetta.tools.minecraft.voyager.gateway import ExecuteMissionRequest
from animetta.tools.minecraft.voyager.goal_models import GoalSpec
from animetta.tools.minecraft.voyager.journal import JournalCommand, StepRecord
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
