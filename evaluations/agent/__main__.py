"""CLI for local agent candidate export, promotion, and release evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
for _path in (str(_PROJECT_ROOT), str(_SRC_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from animetta.config.providers.llm.pricing import ModelPricingV1
from animetta.observability.ledger import SQLiteObservationLedger

from .evaluator import cohen_kappa, cost_regression_passes, evaluate_trajectory, p95_cost
from .models import AgentTrajectoryV1, ModelBudgetV1, trajectory_from_ledger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evaluations.agent")
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export")
    export.add_argument("--ledger", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--limit", type=int, default=500)

    promote = commands.add_parser("promote")
    promote.add_argument("--candidate", type=Path, required=True)
    promote.add_argument("--trace-id")
    promote.add_argument("--content-file", type=Path, required=True)
    promote.add_argument("--output", type=Path, required=True)
    promote.add_argument("--privacy-reviewed", action="store_true")

    run = commands.add_parser("run")
    run.add_argument(
        "--dataset",
        type=Path,
        default=Path("evaluations/agent/datasets/v1.jsonl"),
    )
    run.add_argument(
        "--baseline",
        type=Path,
        default=Path("evaluations/agent/datasets/baseline-v1.json"),
    )
    run.add_argument("--manifest", type=Path, default=Path("config/animetta.yaml"))
    run.add_argument("--output", type=Path)
    return parser


async def export_candidates(ledger_path: Path, output: Path, limit: int) -> int:
    ledger = SQLiteObservationLedger(ledger_path)
    await ledger.start()
    candidates: list[dict[str, Any]] = []
    try:
        for summary in await ledger.recent_traces(limit=max(1, min(limit, 500))):
            detail = await ledger.trace_detail(str(summary["trace_id"]))
            if detail is None:
                continue
            trajectory = trajectory_from_ledger(dict(detail))
            reasons = _candidate_reasons(trajectory)
            if reasons:
                candidates.append(
                    {
                        "schema_version": 1,
                        "trace_id": trajectory.trace_id,
                        "reasons": reasons,
                        "trajectory": trajectory.model_dump(mode="json"),
                        "raw_content_saved": False,
                    }
                )
    finally:
        await ledger.close()
    _write_jsonl(output, candidates)
    return len(candidates)


def promote_candidate(
    candidate_path: Path,
    content_path: Path,
    output: Path,
    *,
    privacy_reviewed: bool,
    trace_id: str | None = None,
) -> None:
    if not privacy_reviewed:
        raise ValueError("promotion requires --privacy-reviewed")
    candidates = _read_jsonl(candidate_path)
    if trace_id is not None:
        candidates = [item for item in candidates if str(item.get("trace_id")) == trace_id]
    if len(candidates) != 1:
        raise ValueError("promotion requires exactly one candidate; provide --trace-id")
    candidate = candidates[0]
    content = json.loads(content_path.read_text(encoding="utf-8"))
    if not isinstance(content, dict) or not content.get("reviewer"):
        raise ValueError("content file must identify the human privacy reviewer")
    if content.get("human_label") not in {"pass", "fail"}:
        raise ValueError("content file human_label must be pass or fail")
    if not isinstance(content.get("expected_pass"), bool):
        raise ValueError("content file must provide boolean expected_pass")
    if not content.get("input") or not content.get("expected"):
        raise ValueError("content file must provide explicitly reviewed input and expected output")
    fixture = {
        "schema_version": 1,
        "id": str(content.get("id") or candidate["trace_id"]),
        "human_label": str(content["human_label"]),
        "judge_label": str(content.get("judge_label") or "unreported"),
        "expected_pass": content["expected_pass"],
        "input": content.get("input"),
        "expected": content.get("expected"),
        "trajectory": candidate["trajectory"],
        "privacy_review": {
            "reviewer": content["reviewer"],
            "reviewed_at": content.get("reviewed_at"),
        },
    }
    _append_jsonl(output, fixture)


def run_dataset(dataset: Path, baseline: Path, manifest: Path) -> dict[str, Any]:
    rows = _read_jsonl(dataset)
    if len(rows) < 30:
        raise ValueError("agent evaluation requires at least 30 human-labelled cases")
    deterministic_passes: list[bool] = []
    costs: list[float] = []
    human: list[str] = []
    judge: list[str] = []
    mismatches: list[str] = []
    for row in rows:
        trajectory = AgentTrajectoryV1.model_validate(row["trajectory"])
        budget = ModelBudgetV1.model_validate(row.get("budget") or {})
        result = evaluate_trajectory(trajectory, budget=budget, production=True)
        expected = bool(row["expected_pass"])
        deterministic_passes.append(result.passed == expected)
        if result.passed != expected:
            mismatches.append(str(row["id"]))
        costs.append(trajectory.total_cost_usd)
        human.append(str(row["human_label"]))
        judge.append(str(row.get("judge_label") or "unreported"))
    baseline_data = json.loads(baseline.read_text(encoding="utf-8"))
    kappa = cohen_kappa(human, judge)
    pricing = _manifest_pricing(manifest)
    pricing_fresh = not pricing.is_stale(today=date.today())
    cost_ok = cost_regression_passes(costs, float(baseline_data["p95_cost_usd"]))
    passed = all(deterministic_passes) and cost_ok and pricing_fresh
    return {
        "schema_version": 1,
        "passed": passed,
        "case_count": len(rows),
        "mismatches": mismatches,
        "p95_cost_usd": p95_cost(costs),
        "baseline_p95_cost_usd": baseline_data["p95_cost_usd"],
        "cost_regression_passed": cost_ok,
        "pricing_fresh": pricing_fresh,
        "judge": {
            "cohen_kappa": kappa,
            "authoritative": False,
            "eligible_for_reporting": kappa >= 0.60,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        count = asyncio.run(export_candidates(args.ledger, args.output, args.limit))
        print(json.dumps({"exported": count, "output": str(args.output)}))
        return 0
    if args.command == "promote":
        promote_candidate(
            args.candidate,
            args.content_file,
            args.output,
            privacy_reviewed=args.privacy_reviewed,
            trace_id=args.trace_id,
        )
        print(json.dumps({"promoted": True, "output": str(args.output)}))
        return 0
    result = run_dataset(args.dataset, args.baseline, args.manifest)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


def _candidate_reasons(trajectory: AgentTrajectoryV1) -> list[str]:
    reasons: list[str] = []
    if trajectory.terminal_status not in {"success", "degraded"}:
        reasons.append("failure")
    if any(step.error_code and "timeout" in step.error_code.lower() for step in trajectory.steps):
        reasons.append("timeout")
    if any(step.approval_result == "reject" for step in trajectory.steps):
        reasons.append("approval_rejected")
    if trajectory.has_duplicate_tool_call:
        reasons.append("duplicate_tool")
    if not evaluate_trajectory(trajectory, production=False).passed:
        reasons.append("budget_or_contract")
    return sorted(set(reasons))


def _manifest_pricing(path: Path) -> ModelPricingV1:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ModelPricingV1.model_validate(raw["providers"]["llm"]["deepseek"]["pricing"])


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
