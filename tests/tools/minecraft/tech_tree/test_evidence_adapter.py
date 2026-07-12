"""TechTreeRunner must not treat inventory or command claims as unlock evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from animetta.tools.gamebot.contracts import (
    ActionOutcome,
    ActionReceipt,
    GameBotObservation,
)
from animetta.tools.minecraft.tech_tree.models import TechTreePhase
from animetta.tools.minecraft.tech_tree.runner import TechTreeRunner
from animetta.tools.minecraft.voyager import tech_graph


def _observation(observation_id: str, inventory: dict[str, int]):
    return GameBotObservation(
        observation_id=observation_id,
        correlation_id=f"corr-{observation_id}",
        runtime_id="runtime-1",
        captured_at=datetime(2026, 7, 12, tzinfo=UTC),
        inventory=inventory,
    )


def _runner() -> TechTreeRunner:
    graph = tech_graph.build_survival_tech_graph()
    return TechTreeRunner(
        MagicMock(),
        MagicMock(),
        evidence_verifier=tech_graph.TechEvidenceVerifier(graph),
        tech_progress=tech_graph.TechProgress(),
        phase_node_map={"wood": "wood_collection"},
    )


def _phase() -> TechTreePhase:
    return TechTreePhase(
        name="wood",
        time_budget_minutes=1,
        required_items={"oak_log": 1},
        skills_to_learn=[],
        description="Evidence adapter test phase",
    )


async def test_evidence_enabled_runner_rejects_inventory_only_milestone() -> None:
    runner = _runner()

    completed = await runner._check_milestone(_phase(), {"oak_log": 64})

    assert completed is False
    assert runner.last_evidence_report is not None
    assert runner.last_evidence_report.failures[0].code == "MISSING_MILESTONE_EVIDENCE"
    assert runner.tech_progress.unlocked_nodes == frozenset()


async def test_evidence_enabled_runner_commits_valid_unlock_record() -> None:
    runner = _runner()
    before = _observation("obs-0", {})
    after = _observation("obs-1", {"oak_log": 1})
    started = datetime(2026, 7, 12, tzinfo=UTC)
    receipt = ActionReceipt(
        receipt_id="receipt-1",
        session_id="session-1",
        task_id="task-1",
        correlation_id="corr-action",
        runtime_id="runtime-1",
        capability="collect",
        params={"block_type": "oak_log", "count": 1},
        started_at=started,
        finished_at=started + timedelta(seconds=1),
        before_observation_hash=before.content_hash,
        after_observation_hash=after.content_hash,
        outcome=ActionOutcome.SUCCESS,
    )
    evidence = tech_graph.TechMilestoneEvidence(
        receipts=(receipt,),
        before=before,
        after=after,
        session_id="session-1",
        task_id="task-1",
        runtime_id="runtime-1",
    )

    completed = await runner._check_milestone(
        _phase(),
        {"oak_log": 1},
        evidence=evidence,
    )

    assert completed is True
    assert runner.tech_progress.unlocked_nodes == {"wood_collection"}
    assert runner.last_evidence_report.unlock_record.node_id == "wood_collection"
