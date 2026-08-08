from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from animetta.tools.minecraft.showcase.promotion import (
    AcceptanceLedger,
    AcceptanceLedgerStore,
    PromotionIdentity,
)
from scripts.minecraft_adaptive_showcase import (
    _record_r8_result,
    _require_r8_start,
    _write_showcase_summary,
)


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


def test_showcase_summary_hashes_final_manifest_file_bytes(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"manifest_hash": "a" * 64}, indent=2),
        encoding="utf-8",
    )
    result = SimpleNamespace(
        dialogue=SimpleNamespace(mission_id="mission-1"),
        evidence=SimpleNamespace(
            mission_report=SimpleNamespace(status="completed"),
            final_narration="真实完成。",
        ),
    )

    summary_path = _write_showcase_summary(
        run_root=tmp_path,
        run_id="run-1",
        result=result,
        projection_url="http://127.0.0.1:43123/minecraft-gameplay.html?runId=run-1",
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert summary["projection_url"].endswith("?runId=run-1")


def test_showcase_entrypoint_checks_durable_r8_promotion_before_start(tmp_path: Path) -> None:
    path = tmp_path / "acceptance-ledger.json"
    ledger = AcceptanceLedger(identity=_identity())
    AcceptanceLedgerStore(path).save(ledger)

    with pytest.raises(ValueError, match="PRIOR_GATE_NOT_PROMOTED"):
        _require_r8_start(path)

    for ordinal in range(8):
        ledger = ledger.record_gate(
            gate=f"R{ordinal}",  # type: ignore[arg-type]
            status="passed",
            attempt_id=f"r{ordinal}-pass",
            started_at_ms=ordinal,
            finished_at_ms=ordinal + 1,
            evidence_refs=(f"artifact:r{ordinal}",),
        )
    AcceptanceLedgerStore(path).save(ledger)

    assert _require_r8_start(path) == ledger


def test_showcase_result_is_recorded_before_another_r8_can_start(tmp_path: Path) -> None:
    ledger_path = tmp_path / "acceptance-ledger.json"
    ledger = AcceptanceLedger(identity=_identity())
    for ordinal in range(8):
        ledger = ledger.record_gate(
            gate=f"R{ordinal}",  # type: ignore[arg-type]
            status="passed",
            attempt_id=f"r{ordinal}-pass",
            started_at_ms=ordinal,
            finished_at_ms=ordinal + 1,
            evidence_refs=(f"artifact:r{ordinal}",),
        )
    AcceptanceLedgerStore(ledger_path).save(ledger)
    run_root = tmp_path / "run-failed"
    (run_root / "manifest.json").parent.mkdir(parents=True)
    (run_root / "manifest.json").write_text("{}", encoding="utf-8")
    (run_root / "showcase-result.json").write_text("{}", encoding="utf-8")
    result = SimpleNamespace(
        evidence=SimpleNamespace(
            mission_report=SimpleNamespace(status="failed"),
            stages=(
                SimpleNamespace(
                    stage_id="construction",
                    lifecycle="failed",
                    started_at_ms=100,
                    finished_at_ms=120,
                    failure=SimpleNamespace(code="PREDICATE_FAILED", layer="verification"),
                ),
            ),
        )
    )

    _record_r8_result(
        ledger_path=ledger_path,
        run_root=run_root,
        run_id="run-failed",
        result=result,
    )

    restored = AcceptanceLedgerStore(ledger_path).load()
    assert restored.real_attempts[-1].stage_id == "construction"
    assert restored.real_attempts[-1].failure_code == "PREDICATE_FAILED"
    assert restored.gate_results[-1].gate == "R8"
    assert restored.gate_results[-1].status == "failed"
    with pytest.raises(ValueError, match="DUPLICATE_REAL_ATTEMPT"):
        _record_r8_result(
            ledger_path=ledger_path,
            run_root=run_root,
            run_id="run-failed",
            result=result,
        )
