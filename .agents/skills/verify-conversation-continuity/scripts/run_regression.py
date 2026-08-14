#!/usr/bin/env python3
"""Run the focused conversation-continuity regression without duplicating its contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
GROUP_ID = "livestream-continuity-contract"
# This mapped test path selects the focused group without Docker actions or wider-group dominance.
PLAN_ANCHOR = "tests/services/llm/test_explicit_history_contract.py"
DEFAULT_OUTPUT = ROOT / "artifacts" / "conversation-continuity" / "skill-evidence.json"


class RegressionError(RuntimeError):
    """A fail-closed regression error carrying a content-free code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _run_command(
    argv: Sequence[str], *, timeout_seconds: float
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RegressionError("subprocess_timeout") from exc
    except OSError as exc:
        raise RegressionError("subprocess_start_failed") from exc


def _require_success(result: subprocess.CompletedProcess[str], code: str) -> None:
    if result.returncode != 0:
        raise RegressionError(code)


def _load_plan(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegressionError("quality_plan_invalid") from exc
    if not isinstance(payload, Mapping):
        raise RegressionError("quality_plan_invalid")
    return payload


def _validate_plan(plan: Mapping[str, Any]) -> None:
    groups = plan.get("groups")
    if not isinstance(groups, list):
        raise RegressionError("quality_plan_invalid")
    group_ids = {
        str(group.get("id")) for group in groups if isinstance(group, Mapping) and group.get("id")
    }
    if GROUP_ID not in group_ids:
        raise RegressionError("continuity_group_missing")
    if "backend-full" in group_ids:
        raise RegressionError("backend_full_selected")
    if plan.get("fallbacks"):
        raise RegressionError("quality_fallback_selected")
    if plan.get("unmapped_paths"):
        raise RegressionError("quality_path_unmapped")
    if plan.get("docker_actions"):
        raise RegressionError("docker_action_selected")


def _run_deterministic() -> None:
    with tempfile.TemporaryDirectory(prefix="animetta-continuity-") as temporary:
        plan_path = Path(temporary) / "plan.json"
        plan_result = _run_command(
            (
                sys.executable,
                "-m",
                "tooling.quality",
                "plan",
                "--tier",
                "affected",
                "--paths",
                PLAN_ANCHOR,
                "--output",
                str(plan_path),
            ),
            timeout_seconds=180,
        )
        _require_success(plan_result, "quality_plan_failed")
        _validate_plan(_load_plan(plan_path))

        group_result = _run_command(
            (
                sys.executable,
                "-m",
                "tooling.quality",
                "run-group",
                GROUP_ID,
                "--plan",
                str(plan_path),
                "--cache",
                "read-write",
                "--trust-scope",
                "local",
                "--json",
            ),
            timeout_seconds=300,
        )
        _require_success(group_result, "continuity_contract_failed")


def _validate_runtime_evidence(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegressionError("continuity_evidence_missing") from exc
    if not isinstance(payload, Mapping):
        raise RegressionError("continuity_evidence_invalid")

    try:
        from scripts.release_runtime_gate import (
            ReleaseGateError,
            validate_conversation_continuity_evidence,
        )

        validate_conversation_continuity_evidence(payload)
    except (ImportError, ReleaseGateError, TypeError, ValueError) as exc:
        raise RegressionError("continuity_evidence_invalid") from exc


def _run_runtime(url: str, output: Path) -> None:
    canary_result = _run_command(
        (
            sys.executable,
            "scripts/conversation_continuity_canary.py",
            "--url",
            url,
            "--output",
            str(output),
        ),
        timeout_seconds=600,
    )
    _require_success(canary_result, "continuity_canary_failed")
    _validate_runtime_evidence(output)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("deterministic", "runtime"),
        default="deterministic",
    )
    parser.add_argument("--url")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    started = time.monotonic()
    evidence_path: str | None = None
    error_codes: list[str] = []

    try:
        if sys.version_info < (3, 13):  # noqa: UP036 - standalone entrypoint enforces repo Python
            raise RegressionError("python_3_13_required")
        if args.mode == "runtime" and not args.url:
            raise RegressionError("runtime_url_required")

        _run_deterministic()
        if args.mode == "runtime":
            output = args.output.resolve()
            evidence_path = str(output)
            _run_runtime(str(args.url), output)
    except RegressionError as exc:
        error_codes.append(exc.code)

    summary = {
        "schema_version": 1,
        "mode": args.mode,
        "status": "passed" if not error_codes else "failed",
        "group_id": GROUP_ID,
        "duration_seconds": round(time.monotonic() - started, 3),
        "evidence_path": evidence_path,
        "error_codes": error_codes,
    }
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    return 0 if not error_codes else 1


if __name__ == "__main__":
    raise SystemExit(main())
