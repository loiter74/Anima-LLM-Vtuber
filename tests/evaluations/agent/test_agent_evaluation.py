from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from evaluations.agent.__main__ import promote_candidate, run_dataset
from evaluations.agent.evaluator import cost_regression_passes, evaluate_trajectory
from evaluations.agent.models import AgentTrajectoryV1, trajectory_from_ledger

ROOT = Path(__file__).resolve().parents[3]


def test_versioned_dataset_passes_all_release_gates() -> None:
    result = run_dataset(
        ROOT / "evaluations/agent/datasets/v1.jsonl",
        ROOT / "evaluations/agent/datasets/baseline-v1.json",
        ROOT / "config/animetta.yaml",
    )

    assert result["passed"] is True
    assert result["case_count"] == 30
    assert result["judge"]["authoritative"] is False
    assert result["judge"]["cohen_kappa"] >= 0.60


def test_stale_pricing_blocks_release_gate(tmp_path: Path) -> None:
    manifest = yaml.safe_load((ROOT / "config/animetta.yaml").read_text(encoding="utf-8"))
    manifest["providers"]["llm"]["deepseek"]["pricing"]["verified_on"] = (
        date.today() - timedelta(days=91)
    ).isoformat()
    stale_manifest = tmp_path / "animetta.yaml"
    stale_manifest.write_text(yaml.safe_dump(manifest), encoding="utf-8")

    result = run_dataset(
        ROOT / "evaluations/agent/datasets/v1.jsonl",
        ROOT / "evaluations/agent/datasets/baseline-v1.json",
        stale_manifest,
    )

    assert result["passed"] is False
    assert result["pricing_fresh"] is False


def test_cost_p95_cannot_regress_over_twenty_percent() -> None:
    assert cost_regression_passes([0.006], 0.005)
    assert not cost_regression_passes([0.00601], 0.005)


def test_deterministic_evaluator_catches_safety_recovery_and_latency() -> None:
    trajectory = AgentTrajectoryV1.model_validate(
        {
            "trace_id": "negative",
            "runtime_profile": "production",
            "terminal_status": "success",
            "steps": [
                {
                    "kind": "tool",
                    "name": "unknown_mcp",
                    "status": "success",
                    "policy_decision": "deny",
                    "parameters_valid": False,
                    "latency_ms": 30_001,
                    "request_id": "same",
                    "recovered": True,
                },
                {
                    "kind": "tool",
                    "name": "another_tool",
                    "status": "success",
                    "request_id": "same",
                    "recovered": True,
                },
            ],
        }
    )

    codes = {finding.code for finding in evaluate_trajectory(trajectory).findings}

    assert {
        "DISABLED_TOOL_EXECUTED",
        "PARAMETER_CONSTRAINT_VIOLATION",
        "TOOL_LATENCY_EXCEEDED",
        "RECOVERY_IDEMPOTENCY_FAILED",
    } <= codes


def test_production_evaluator_rejects_llm_step_without_provider_usage() -> None:
    trajectory = AgentTrajectoryV1.model_validate(
        {
            "trace_id": "missing-usage",
            "runtime_profile": "production",
            "terminal_status": "success",
            "steps": [
                {
                    "kind": "node",
                    "name": "llm.chat",
                    "status": "success",
                    "input_tokens": 20,
                }
            ],
        }
    )

    codes = {finding.code for finding in evaluate_trajectory(trajectory).findings}

    assert "PROVIDER_USAGE_MISSING" in codes


def test_ledger_export_is_ordered_redacted_and_keeps_approval_evidence() -> None:
    trajectory = trajectory_from_ledger(
        {
            "trace_id": "trace",
            "runtime_profile": "production",
            "outcome": "success",
            "duration_ms": 30,
            "operations": [
                {
                    "name": "approval:mc_connection",
                    "status": "success",
                    "duration_ms": 1,
                    "attributes": {"approval_result": "approve"},
                },
                {
                    "name": "tool:mc_connection",
                    "status": "success",
                    "duration_ms": 10,
                    "attributes": {
                        "arguments_digest": "digest-only",
                        "retry_count": 0,
                        "minecraft_request_id": "request-1",
                        "tool_effect": "state_changing",
                    },
                },
            ],
        }
    )

    assert trajectory.raw_content_saved is False
    assert trajectory.steps[0].approval_result == "approve"
    assert trajectory.steps[1].argument_digest == "digest-only"
    assert trajectory.steps[1].request_id == "request-1"
    assert trajectory.steps[1].tool_effect == "state_changing"


def test_promotion_requires_explicit_content_and_privacy_review(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.json"
    content = tmp_path / "content.json"
    output = tmp_path / "fixtures.jsonl"
    candidate.write_text(
        json.dumps(
            {
                "trace_id": "trace",
                "trajectory": {
                    "trace_id": "trace",
                    "runtime_profile": "production",
                    "steps": [],
                    "terminal_status": "failed",
                },
            }
        ),
        encoding="utf-8",
    )
    content.write_text(
        json.dumps(
            {
                "id": "reviewed",
                "human_label": "fail",
                "expected_pass": False,
                "input": "explicitly supplied",
                "expected": "safe refusal",
                "reviewer": "human-reviewer",
                "reviewed_at": "2026-08-15",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="privacy-reviewed"):
        promote_candidate(candidate, content, output, privacy_reviewed=False)

    incomplete = json.loads(content.read_text(encoding="utf-8"))
    incomplete.pop("input")
    content.write_text(json.dumps(incomplete), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed input"):
        promote_candidate(candidate, content, output, privacy_reviewed=True)
    incomplete["input"] = "explicitly supplied"
    content.write_text(json.dumps(incomplete), encoding="utf-8")

    promote_candidate(candidate, content, output, privacy_reviewed=True)
    promoted = json.loads(output.read_text(encoding="utf-8"))
    assert promoted["input"] == "explicitly supplied"
    assert promoted["privacy_review"]["reviewer"] == "human-reviewer"
