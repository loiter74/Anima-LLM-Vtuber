"""Classify legacy real-showcase evidence into the durable acceptance ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .promotion import FailureLayer, RealAttempt


def _objects(value: object) -> tuple[dict[str, Any], ...]:
    if isinstance(value, dict):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, dict))
    return ()


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _nested_dict(value: object, *keys: str) -> dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


class HistoricalShowcaseClassifier:
    """Conservatively map old bundles without inventing unavailable detail."""

    def classify(self, run_root: Path) -> RealAttempt:
        resolved = run_root.resolve()
        artifact_root = resolved / "artifacts"
        command_path = artifact_root / "commands.json"
        receipt_path = artifact_root / "receipts.json"
        status_path = artifact_root / "final-status.json"
        commands = _objects(_load(command_path))
        receipts = _objects(_load(receipt_path))
        final_status = _load(status_path)
        failed = next(
            (
                command
                for command in reversed(commands)
                if not str(command.get("state", "")).startswith("succeeded")
            ),
            None,
        )
        if failed is None:
            raise ValueError("HISTORICAL_RUN_HAS_NO_FAILED_COMMAND")

        payload = _nested_dict(failed, "payload")
        goal = _nested_dict(payload, "goal")
        objective_id = str(payload.get("objective_id", ""))
        state = str(failed.get("state", ""))
        stage_id = self._stage_id(goal)
        terminal_error = _nested_dict(failed, "terminal_result", "error")
        receipt_error = next(
            (error for receipt in reversed(receipts) if (error := _nested_dict(receipt, "error"))),
            {},
        )
        failure_code = str(terminal_error.get("code") or receipt_error.get("code") or "")
        if not failure_code:
            verification = self._objective_verification(final_status, objective_id)
            successful_action = any(receipt.get("outcome") == "success" for receipt in receipts)
            if state == "blocked_unknown":
                failure_code = "LEGACY_BLOCKED_UNKNOWN"
            elif state == "failed_reconciled":
                failure_code = "LEGACY_RECONCILIATION_FAILED"
            elif verification == "failed" and successful_action:
                failure_code = "LEGACY_GOAL_VERIFICATION_FAILED"
            else:
                failure_code = "LEGACY_COMMAND_FAILED"

        occurred_at_ms = int(
            failed.get("terminal_at_ms")
            or failed.get("started_at_ms")
            or failed.get("accepted_at_ms")
            or 0
        )
        return RealAttempt(
            attempt_id=f"historical:{resolved.name}",
            run_id=resolved.name,
            stage_id=stage_id,
            outcome="failed",
            failure_code=failure_code,
            failure_layer=self._failure_layer(failure_code),
            occurred_at_ms=occurred_at_ms,
            evidence_refs=tuple(
                f"file:{path.resolve().as_posix()}"
                for path in (command_path, receipt_path, status_path)
            ),
        )

    @staticmethod
    def _stage_id(goal: dict[str, Any]) -> str:
        intent = str(goal.get("intent", ""))
        if intent == "combat":
            return "combat"
        if intent == "build":
            return "construction"
        if intent == "travel":
            return "autonomous-exploration"
        if intent == "acquire":
            phase = str(_nested_dict(goal, "constraints").get("adaptive_phase", ""))
            if phase == "learn_validate":
                return "skill-learning-validation"
            if phase == "reuse":
                return "skill-reuse"
            return "discovery-acquisition"
        raise ValueError(f"UNSUPPORTED_HISTORICAL_GOAL_INTENT:{intent}")

    @staticmethod
    def _failure_layer(code: str) -> FailureLayer:
        if code in {
            "LEGACY_BLOCKED_UNKNOWN",
            "LEGACY_RECONCILIATION_FAILED",
            "POST_ACTION_OBSERVATION_UNSTABLE",
            "UNEXPLAINED_STATE_DELTA",
        }:
            return "reconciliation"
        if "VERIFICATION" in code:
            return "verification"
        return "execution"

    @staticmethod
    def _objective_verification(final_status: object, objective_id: str) -> str:
        if not isinstance(final_status, dict):
            return ""
        for mission in _objects(final_status.get("missions")):
            for objective in _objects(mission.get("objectives")):
                if objective.get("objective_id") == objective_id:
                    return str(objective.get("verification", ""))
        return ""
