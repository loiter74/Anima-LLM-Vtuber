"""Mocked acceptance chain across gateway, strategies, trust, status, and stop."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from animetta.tools.gamebot.contracts.v2 import Observation, RuntimeManifest
from animetta.tools.minecraft.skill.applicability import applicability_for_goal
from animetta.tools.minecraft.skill.trust import (
    SkillEnvironmentTrust,
    stable_environment_fingerprint,
)
from animetta.tools.minecraft.survival.registry import WorkflowRegistry
from animetta.tools.minecraft.survival.workflows import iron_survival_workflow
from animetta.tools.minecraft.voyager.budget import (
    BudgetUsage,
    ExecutionBudget,
    ModeBudgetPolicy,
)
from animetta.tools.minecraft.voyager.gateway import ExecuteAtomicRequest, VoyagerGateway
from animetta.tools.minecraft.voyager.goal_models import AtomicAction, GoalSpec
from animetta.tools.minecraft.voyager.journal import InMemoryCommandJournal
from animetta.tools.minecraft.voyager.stop import GlobalStopBarrier
from animetta.tools.minecraft.voyager.strategies.atomic import AtomicStrategy
from animetta.tools.minecraft.voyager.strategies.fallback import FallbackStrategy
from animetta.tools.minecraft.voyager.strategies.learn import LearnStrategy
from animetta.tools.minecraft.voyager.strategies.live import LiveStrategy

ROOT = Path(__file__).resolve().parents[4]
MESSAGES = json.loads(
    (ROOT / "contracts/gamebot/v2/fixtures/golden.json").read_text(encoding="utf-8")
)["messages"]


def _goal() -> GoalSpec:
    return TypeAdapter(GoalSpec).validate_python(
        {
            "intent": "acquire",
            "target": "iron_ingot",
            "quantity": 1,
            "success_predicates": [
                {"kind": "inventory_at_least", "item": "iron_ingot", "quantity": 1}
            ],
        }
    )


def _budget() -> ExecutionBudget:
    return ExecutionBudget(
        queue_timeout_ms=1_000,
        execution_timeout_ms=10_000,
        max_actions=16,
        max_strategy_attempts=4,
        max_travel_distance=256,
        max_blocks_changed=64,
        max_damage_taken=4,
    )


async def _noop(*_args) -> None:
    return None


async def test_atomic_learn_validate_live_fallback_status_stop_chain() -> None:
    manifest = RuntimeManifest.model_validate(MESSAGES["RuntimeManifest"])
    observation = Observation.model_validate(MESSAGES["Observation"])

    atomic = AtomicStrategy(
        action=AtomicAction(capability="collect", parameters={"count": 1}),
        manifest=manifest,
    )
    assert atomic.propose(atomic.prepare(None), observation).kind == "execute"

    learn = LearnStrategy(
        resolve_frontier=lambda _goal: ("iron_ingot",),
        propose_node=lambda node: {
            "node": node,
            "capability": "collect",
            "parameters": {"count": 1},
            "maximum_cost": BudgetUsage(max_actions=1),
        },
        max_frontier_nodes=1,
        max_attempts=2,
        manifest=manifest,
        compilation_budget=_budget(),
        source_command_id="learn-command",
    )
    state = learn.prepare(_goal())
    state = learn.accept_result(state, {"receipt_hash": "a" * 64})
    state = learn.accept_result(state, {"receipt_hash": "b" * 64})
    learned = learn.propose(state, observation)
    revision = learned.output["candidate_revisions"][0]
    trust = SkillEnvironmentTrust.trusted(
        revision.revision_hash,
        stable_environment_fingerprint(manifest.profile),
        successes=1,
    )

    live = LiveStrategy(
        revisions={revision.revision_hash: revision},
        applicabilities={revision.revision_hash: applicability_for_goal(revision, _goal())},
        trusts=[trust],
        manifest=manifest,
    )
    assert live.propose(live.prepare(_goal()), observation).kind == "execute"

    registry = WorkflowRegistry()
    registry.register(iron_survival_workflow())
    fallback = FallbackStrategy(registry=registry)
    fallback_state = fallback.prepare(_goal())
    assert fallback.propose(fallback_state, observation).kind == "execute"
    assert fallback_state["learning_evidence_eligible"] is False

    repository = InMemoryCommandJournal()
    barrier = GlobalStopBarrier(repository=repository, signal_active=_noop, now_ms=lambda: 100)
    policy = ModeBudgetPolicy(atomic=_budget(), learn=_budget(), live=_budget(), fallback=_budget())
    gateway = VoyagerGateway(
        repository=repository,
        stop_barrier=barrier,
        manifest=manifest,
        budget_policy=policy,
        now_ms=lambda: 100,
        make_id=lambda prefix: f"{prefix}-acceptance",
    )
    handle = await gateway.execute(
        caller_scope="principal:acceptance",
        request=ExecuteAtomicRequest(
            contract_version="2",
            kind="atomic",
            request_id="acceptance-atomic",
            action=AtomicAction(capability="collect", parameters={"count": 1}),
        ),
    )
    status = await gateway.status(caller_scope="principal:acceptance")
    stopped = await gateway.stop(
        caller_scope="principal:acceptance",
        request_id="acceptance-stop",
        reason="acceptance complete",
    )

    assert status.commands[0].command_id == handle.command_id
    assert stopped.cancelled_command_ids == (handle.command_id,)
