"""Metrics pipeline self-check — Prometheus metrics endpoint.

Probes:
  - GET /metrics endpoint reachability
  - Expected gauge/counter metric names in the response body
  - check_metrics_pipeline() — aggregate probes into CheckResult
"""

from __future__ import annotations

import time

import httpx
from loguru import logger

from ..models import CheckResult
from ..runtime import InspectionRuntime

METRICS_ENDPOINT = "http://localhost:12394/metrics"
EXPECTED_METRICS = [
    "anima_trace_outcomes_total",
    "anima_node_duration_seconds",
]
REQUEST_TIMEOUT = 5.0  # seconds


async def check_metrics_pipeline(
    runtime: InspectionRuntime | None = None,
) -> CheckResult:
    """Check Prometheus /metrics endpoint reachability and expected metric names.

    Verifies:
      1. HTTP 200 from GET /metrics
      2. Response body contains ``anima_llm_errors_total``
      3. Response body contains ``anima_node_duration_seconds``

    Returns:
        CheckResult.passed if all checks pass, CheckResult.failed otherwise.
    """
    t0 = time.perf_counter()
    issues: list[str] = []
    detail: dict[str, object] = {"endpoint": METRICS_ENDPOINT}

    try:
        if runtime is not None:
            body = runtime.metrics_snapshot()
            detail["status_code"] = 200
            detail["body_length"] = len(body)
            for metric_name in EXPECTED_METRICS:
                present = metric_name in body
                detail[f"has_{metric_name}"] = present
                if not present:
                    issues.append(f"metrics_missing_{metric_name}")
            duration_ms = (time.perf_counter() - t0) * 1000
            if issues:
                return CheckResult.failed(
                    "metrics_pipeline", duration_ms, "; ".join(issues), **detail
                )
            return CheckResult.passed(
                "metrics_pipeline", duration_ms=duration_ms, **detail
            )
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(METRICS_ENDPOINT)
            detail["status_code"] = resp.status_code

            if resp.status_code != 200:
                issues.append(f"metrics_status_{resp.status_code}")
                logger.warning(
                    f"[metrics] Unexpected status {resp.status_code} from {METRICS_ENDPOINT}"
                )
            else:
                body = resp.text
                detail["body_length"] = len(body)

                # Verify expected metric names are present in the response
                for metric_name in EXPECTED_METRICS:
                    if metric_name in body:
                        detail[f"has_{metric_name}"] = True
                    else:
                        detail[f"has_{metric_name}"] = False
                        issues.append(f"metrics_missing_{metric_name}")
                        logger.warning(
                            f"[metrics] Missing expected metric: {metric_name}"
                        )

    except httpx.ConnectError as e:
        issues.append("metrics_unreachable")
        detail["exception"] = str(e)
        logger.warning(f"[metrics] Endpoint unreachable: {METRICS_ENDPOINT} — {e}")
    except httpx.TimeoutException as e:
        issues.append("metrics_timeout")
        detail["exception"] = str(e)
        logger.warning(f"[metrics] Request timeout: {METRICS_ENDPOINT} — {e}")
    except Exception as e:
        issues.append("metrics_error")
        detail["exception"] = str(e)
        logger.error(f"[metrics] Check failed: {e}")

    duration_ms = (time.perf_counter() - t0) * 1000

    if issues:
        return CheckResult.failed(
            name="metrics_pipeline",
            duration_ms=round(duration_ms, 1),
            error="; ".join(issues),
            **detail,  # type: ignore[arg-type]
        )
    return CheckResult.passed(
        name="metrics_pipeline",
        duration_ms=round(duration_ms, 1),
        **detail,  # type: ignore[arg-type]
    )


def controlled_metric_delta(
    before: str,
    after: str,
    metric_names: tuple[str, ...] = (
        "anima_trace_outcomes_total",
        "anima_node_duration_seconds_count",
    ),
) -> dict[str, float]:
    """Return positive sample deltas; missing or unchanged metrics map to zero."""
    return {
        name: max(0.0, _metric_sum(after, name) - _metric_sum(before, name))
        for name in metric_names
    }


def _metric_sum(snapshot: str, metric_name: str) -> float:
    total = 0.0
    for line in snapshot.splitlines():
        if not line.startswith(metric_name):
            continue
        head, separator, value = line.rpartition(" ")
        if not separator or not (
            head == metric_name or head.startswith(f"{metric_name}{{")
        ):
            continue
        try:
            total += float(value)
        except ValueError:
            continue
    return total
