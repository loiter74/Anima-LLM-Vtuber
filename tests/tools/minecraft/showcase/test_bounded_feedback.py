from __future__ import annotations

import json
from types import SimpleNamespace

from animetta.tools.minecraft.showcase.promotion import (
    AcceptanceLedger,
    AcceptanceLedgerStore,
    PromotionIdentity,
)
from scripts.minecraft_adaptive_micro_gate import _FeedbackJournal, _record_r7_result
from scripts.minecraft_adaptive_showcase import _MissionFeedbackWriter


def _identity() -> PromotionIdentity:
    return PromotionIdentity(
        code_commit="0123456789abcdef0123456789abcdef01234567",
        code_tree_hash="a" * 64,
        runtime_identity="runtime-a",
        minecraft_version="1.21",
        scenario_hash="b" * 64,
        model_identity="model-a",
        schema_hashes={"stage_io_v2": "c" * 64},
    )


async def test_r7_feedback_journal_publishes_independent_atomic_step_results(tmp_path) -> None:
    journal = _FeedbackJournal(tmp_path / "feedback")

    await journal.publish(
        "combat-zombie",
        "in_progress",
        "two transitions committed",
        ("mission:one:transitions:2",),
        "mission:one:transition:2",
    )
    await journal.publish(
        "combat-zombie",
        "passed",
        "combat completed",
        ("receipt:attack:1",),
        "mission:one:transition:3",
    )

    paths = sorted((tmp_path / "feedback").glob("*.json"))
    assert len(paths) == 2
    assert json.loads(paths[0].read_text(encoding="utf-8"))["status"] == "in_progress"
    assert json.loads(paths[1].read_text(encoding="utf-8"))["status"] == "passed"
    assert not tuple(tmp_path.rglob("*.tmp"))


async def test_r8_live_feedback_is_transition_backed_and_resumable(tmp_path) -> None:
    writer = _MissionFeedbackWriter(tmp_path / "feedback")
    snapshot = SimpleNamespace(
        mission=SimpleNamespace(status=SimpleNamespace(value="running")),
        transitions=(SimpleNamespace(transition_id="transition-7"),),
    )

    await writer("mission-one", snapshot, 125.0)

    path = next((tmp_path / "feedback").glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "in_progress"
    assert payload["latest_transition_id"] == "transition-7"
    assert payload["checkpoint"] == "mission:mission-one:transition:1"
    assert "without resubmission" in payload["next_action"]


def test_r7_ledger_settlement_is_required_before_r8_can_start(tmp_path) -> None:
    ledger_path = tmp_path / "acceptance-ledger.json"
    ledger = AcceptanceLedger(identity=_identity())
    for ordinal in range(7):
        ledger = ledger.record_gate(
            gate=f"R{ordinal}",  # type: ignore[arg-type]
            status="passed",
            attempt_id=f"r{ordinal}-pass",
            started_at_ms=ordinal,
            finished_at_ms=ordinal + 1,
            evidence_refs=(f"artifact:r{ordinal}",),
        )
    AcceptanceLedgerStore(ledger_path).save(ledger)
    artifact_path = tmp_path / "micro-gate.json"
    artifact_path.write_text("{}", encoding="utf-8")

    _record_r7_result(
        ledger_path=ledger_path,
        artifact_path=artifact_path,
        run_id="run-r7",
        started_at_ms=100,
        finished_at_ms=200,
    )

    restored = AcceptanceLedgerStore(ledger_path).load()
    assert restored.real_attempts[-1].stage_id == "ledger-settlement"
    assert restored.gate_results[-1].gate == "R7"
    assert restored.gate_results[-1].status == "passed"
    restored.require_gate_start("R8")
