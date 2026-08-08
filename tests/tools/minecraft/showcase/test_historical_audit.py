from __future__ import annotations

import json
from pathlib import Path

from animetta.tools.minecraft.showcase.historical_audit import (
    HistoricalShowcaseClassifier,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_fixture(
    tmp_path: Path,
    *,
    run_id: str,
    intent: str,
    state: str,
    terminal_error: str | None = None,
    receipt_error: str | None = None,
    adaptive_phase: str | None = None,
) -> Path:
    run_root = tmp_path / run_id
    constraints = {} if adaptive_phase is None else {"adaptive_phase": adaptive_phase}
    terminal_result = None if terminal_error is None else {"error": {"code": terminal_error}}
    _write_json(
        run_root / "artifacts" / "commands.json",
        {
            "command_id": f"command-{run_id}",
            "state": state,
            "terminal_at_ms": 1234,
            "terminal_result": terminal_result,
            "payload": {
                "objective_id": f"objective-{run_id}",
                "goal": {"intent": intent, "constraints": constraints},
            },
        },
    )
    receipts: list[dict[str, object]] = []
    if receipt_error is not None:
        receipts.append(
            {
                "capability": "place",
                "outcome": "error",
                "error": {"code": receipt_error},
            }
        )
    _write_json(run_root / "artifacts" / "receipts.json", receipts)
    _write_json(
        run_root / "artifacts" / "final-status.json",
        {
            "missions": [
                {
                    "objectives": [
                        {
                            "objective_id": f"objective-{run_id}",
                            "persisted_status": (
                                "blocked_unknown" if "blocked" in state else "failed"
                            ),
                            "verification": ("unknown" if "blocked" in state else "failed"),
                        }
                    ]
                }
            ]
        },
    )
    return run_root


def test_classifier_prefers_typed_terminal_error_and_maps_adaptive_stage(tmp_path: Path) -> None:
    run_root = _run_fixture(
        tmp_path,
        run_id="adaptive-showcase-final20",
        intent="acquire",
        state="blocked_unknown",
        terminal_error="UNEXPLAINED_STATE_DELTA",
        adaptive_phase="learn_validate",
    )

    attempt = HistoricalShowcaseClassifier().classify(run_root)

    assert attempt.run_id == "adaptive-showcase-final20"
    assert attempt.stage_id == "skill-learning-validation"
    assert attempt.failure_code == "UNEXPLAINED_STATE_DELTA"
    assert attempt.failure_layer == "reconciliation"
    assert attempt.occurred_at_ms == 1234
    assert len(attempt.evidence_refs) == 3


def test_classifier_uses_receipt_error_before_legacy_fallback(tmp_path: Path) -> None:
    run_root = _run_fixture(
        tmp_path,
        run_id="adaptive-showcase-final10",
        intent="build",
        state="failed",
        receipt_error="ACTION_FAILED",
    )

    attempt = HistoricalShowcaseClassifier().classify(run_root)

    assert attempt.stage_id == "construction"
    assert attempt.failure_code == "ACTION_FAILED"
    assert attempt.failure_layer == "execution"


def test_classifier_marks_legacy_successful_actions_as_verification_failure(
    tmp_path: Path,
) -> None:
    run_root = _run_fixture(
        tmp_path,
        run_id="adaptive-showcase-final19",
        intent="acquire",
        state="failed",
        adaptive_phase="reuse",
    )
    _write_json(
        run_root / "artifacts" / "receipts.json",
        [{"capability": "collect", "outcome": "success", "error": None}],
    )

    attempt = HistoricalShowcaseClassifier().classify(run_root)

    assert attempt.stage_id == "skill-reuse"
    assert attempt.failure_code == "LEGACY_GOAL_VERIFICATION_FAILED"
    assert attempt.failure_layer == "verification"
