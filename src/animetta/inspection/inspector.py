"""Inspection runner — executes all checks and aggregates results."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from loguru import logger

from .checks import (
    check_all_components,
    check_data_consistency,
    check_golden_conversation_pipeline,
    check_metrics_pipeline,
)
from .models import CheckResult, InspectionReport


async def run_full_inspection() -> InspectionReport:
    """Run all registered inspection checks and return an aggregated report.

    Executes four check categories sequentially:
      1. Component health     — check_all_components()
      2. Pipeline smoke test  — check_conversation_pipeline()
      3. Data consistency     — check_data_consistency()
      4. Metrics pipeline     — check_metrics_pipeline()

    Each check is wrapped in try/except so one failure does not abort
    the remaining checks. Crashed checks produce a CheckResult.failed().

    This is the public entry point. Called by the scheduler for periodic
    runs or by an external API endpoint for manual inspection triggers.

    Returns:
        InspectionReport with all check results and aggregated pass/fail.
    """
    started_at = datetime.now(UTC).timestamp()
    checks: dict[str, CheckResult] = {}
    t0 = time.perf_counter()

    logger.info("[inspection] Starting full inspection")

    # ── 1. Component health checks ──────────────────────────────
    try:

        results = await check_all_components()
        checks.update(results)
    except Exception as exc:
        logger.error(f"[inspection] check_all_components crashed: {exc}")
        checks["health"] = CheckResult.failed(
            "health",
            error=f"check_all_components crashed: {exc}",
        )

    # ── 2. Pipeline smoke test ──────────────────────────────────
    try:

        result = await check_golden_conversation_pipeline()
        checks[result.name] = result
    except Exception as exc:
        logger.error(f"[inspection] check_conversation_pipeline crashed: {exc}")
        checks["pipeline/conversation"] = CheckResult.failed(
            "pipeline/conversation",
            error=f"check_conversation_pipeline crashed: {exc}",
        )

    # ── 3. Data consistency checks ──────────────────────────────
    try:

        result = await check_data_consistency()
        checks[result.name] = result
    except Exception as exc:
        logger.error(f"[inspection] check_data_consistency crashed: {exc}")
        checks["data_consistency"] = CheckResult.failed(
            "data_consistency",
            error=f"check_data_consistency crashed: {exc}",
        )

    # ── 4. Metrics pipeline checks ──────────────────────────────
    try:

        result = await check_metrics_pipeline()
        checks[result.name] = result
    except Exception as exc:
        logger.error(f"[inspection] check_metrics_pipeline crashed: {exc}")
        checks["metrics_pipeline"] = CheckResult.failed(
            "metrics_pipeline",
            error=f"check_metrics_pipeline crashed: {exc}",
        )

    # ── Build frozen report ─────────────────────────────────────
    finished_at = datetime.now(UTC).timestamp()
    duration_sec = time.perf_counter() - t0

    report = InspectionReport(
        started_at=started_at,
        finished_at=finished_at,
        checks=checks,
    )

    logger.info(
        f"[inspection] Inspection {report.run_id[:8]} complete in {duration_sec:.1f}s"
    )
    logger.info(f"[inspection] {report.summary}")

    return report
