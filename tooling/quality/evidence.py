from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .models import AggregateSummary, VerificationPlan, VerificationResult
from .planner import verification_plan_hash


def _write_model(model: BaseModel, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_plan(plan: VerificationPlan, path: str | Path) -> None:
    _write_model(plan, path)


def read_plan(path: str | Path) -> VerificationPlan:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = VerificationPlan.model_validate(payload)
    if plan.plan_hash != verification_plan_hash(plan):
        raise ValueError("plan hash does not match plan contents")
    return plan


def read_results(directory: str | Path) -> list[VerificationResult]:
    root = Path(directory)
    results: list[VerificationResult] = []
    for path in sorted(root.glob("*.json")):
        if path.name in {"summary.json", "feedback-plan.json"}:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        results.append(VerificationResult.model_validate(payload))
    return results


def write_summary(summary: AggregateSummary, path: str | Path) -> None:
    _write_model(summary, path)
