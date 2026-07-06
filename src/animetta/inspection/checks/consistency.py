"""Data consistency checks — StatsStore, Chroma, log files.

Probes:
  - stats_store_responds() — verify StatsStore SQLite reachability
  - has_trace_in_last(minutes) — query traces table for recent activity
  - chroma_responds() — check ChromaDB reachability
  - log_file_stale(minutes) — verify server log file freshness
  - check_data_consistency() — aggregate all probes into CheckResult
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from animetta.orchestration.graph.stats_store import get_stats_store

from ..models import CheckResult

# Project root relative to this file: 5 levels up
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent


async def stats_store_responds() -> bool:
    """Check if StatsStore is reachable with a lightweight SQLite query.

    Returns:
        True if the StatsStore connection is initialized and can answer a
        simple read query.
    """
    try:
        store = await get_stats_store()
        if store._db is None:
            logger.warning("[consistency] StatsStore database not initialized")
            return False
        cursor = await store._db.execute("SELECT 1")
        row = await cursor.fetchone()
        return row is not None and row[0] == 1
    except Exception as e:
        logger.error(f"[consistency] stats_store_responds failed: {e}")
        return False


async def has_trace_in_last(minutes: int) -> bool:
    """Check if there is at least one trace in the last N minutes.

    Queries the StatsStore SQLite database for traces with created_at
    within the specified time window.

    Args:
        minutes: Look-back window in minutes.

    Returns:
        True if at least one trace was created in the last N minutes.
    """
    try:
        store = await get_stats_store()
        if store._db is None:
            logger.warning("[consistency] StatsStore database not initialized")
            return False
        cursor = await store._db.execute(
            "SELECT COUNT(*) FROM traces WHERE created_at >= datetime('now', '-' || ? || ' minutes')",
            (str(minutes),),
        )
        row = await cursor.fetchone()
        return row is not None and row[0] > 0
    except Exception as e:
        logger.error(f"[consistency] has_trace_in_last failed: {e}")
        return False


async def chroma_responds() -> bool:
    """Check if ChromaDB is reachable by attempting to list collections.

    Creates a PersistentClient at the project's default chroma path
    and tries a lightweight operation to verify connectivity.

    Returns:
        True if ChromaDB responds, False on any exception.
    """
    try:
        import chromadb

        persist_dir = str(_PROJECT_ROOT / "data" / "chroma_db")
        client = chromadb.PersistentClient(path=persist_dir)
        collections = client.list_collections()
        logger.info(f"[consistency] Chroma reachable with {len(collections)} collection(s)")
        logger.debug(f"[consistency] Chroma collection count: {len(collections)}")
        return True
    except Exception as e:
        logger.warning(f"[consistency] Chroma unreachable: {e}")
        return False


def log_file_stale(minutes: int) -> bool:
    """Check if the log file is stale (missing or older than N minutes).

    Uses the same log path as the main server: <project_root>/logs/animetta.log.

    Args:
        minutes: Maximum allowed age in minutes.

    Returns:
        True if the log file is missing or its mtime exceeds the threshold.
    """
    try:
        log_path = _PROJECT_ROOT / "logs" / "animetta.log"
        if not log_path.exists():
            logger.warning(f"[consistency] Log file missing: {log_path}")
            return True
        mtime = log_path.stat().st_mtime
        age_seconds = time.time() - mtime
        stale = age_seconds > minutes * 60
        if stale:
            logger.warning(
                f"[consistency] Log file stale: {log_path} (age {age_seconds:.0f}s > {minutes * 60}s)"
            )
        return stale
    except Exception as e:
        logger.error(f"[consistency] log_file_stale check failed: {e}")
        return True


async def check_data_consistency() -> CheckResult:
    """Run all data consistency probes and return a CheckResult.

    Probes:
      1. StatsStore SQLite reachability
      2. Recent traces in StatsStore (diagnostic only)
      3. ChromaDB reachability
      4. Log file freshness (last 60 minutes)

    Returns:
        CheckResult.passed if all probes healthy, CheckResult.failed with
        diagnostic detail otherwise.
    """
    t0 = time.perf_counter()
    issues: list[str] = []
    detail: dict[str, object] = {}

    # ── Probe 1: StatsStore reachability ──
    stats_ok = await stats_store_responds()
    detail["stats_store_ok"] = stats_ok
    if not stats_ok:
        issues.append("stats_store_unreachable")

    # ── Probe 2: StatsStore recent traces (diagnostic only) ──
    has_traces = await has_trace_in_last(minutes=60) if stats_ok else False
    detail["stats_has_recent_trace"] = has_traces

    # ── Probe 3: ChromaDB reachability ──
    chroma_ok = await chroma_responds()
    detail["chroma_ok"] = chroma_ok
    if not chroma_ok:
        issues.append("chroma_unreachable")

    # ── Probe 4: Log file freshness ──
    stale = log_file_stale(minutes=60)
    detail["log_file_stale"] = stale
    if stale:
        issues.append("log_file_stale")

    duration_ms = (time.perf_counter() - t0) * 1000
    detail["issues"] = issues

    if issues:
        return CheckResult.failed(
            name="data_consistency",
            duration_ms=round(duration_ms, 1),
            error="; ".join(issues),
            **detail,  # type: ignore[arg-type]
        )
    return CheckResult.passed(
        name="data_consistency",
        duration_ms=round(duration_ms, 1),
        **detail,  # type: ignore[arg-type]
    )
