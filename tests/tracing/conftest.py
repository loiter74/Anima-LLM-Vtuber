"""Fixtures for tracing tests — resets module-level state between tests.

Problem 1 (test_metrics.py):
    init_metrics() registers Prometheus collectors (PromCounter, PromHistogram)
    on the global REGISTRY. Tests reset ``_initialized`` but never unregister,
    causing ``ValueError: Duplicated timeseries in CollectorRegistry``.

Problem 2 (test_bootstrap.py):
    ``_TRACER_INITIALIZED`` becomes ``True`` after the first init_tracing()
    call and never resets, so subsequent tests hit the early-return guard
    and mocked code is never called.
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

# Prometheus metric names registered by metrics.init_metrics()
_PROM_METRIC_NAMES = [
    "anima_llm_errors_total",
    "anima_node_duration_seconds",
]


def _unregister_prom_collectors() -> None:
    """Remove Prometheus collectors registered by metrics.init_metrics()."""
    for name in _PROM_METRIC_NAMES:
        try:
            collector = REGISTRY._names_to_collectors.get(name)
            if collector is not None:
                REGISTRY.unregister(collector)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _reset_tracing_state():
    """Reset all tracing module globals before and after each test."""
    # ── Before test ──

    # Bootstrap flag
    from animetta.tracing import bootstrap
    bootstrap._TRACER_INITIALIZED = False

    # Metrics flags + singletons
    from animetta.tracing import metrics
    metrics._initialized = False
    metrics._meter = None
    metrics._PROM_LLM_ERRORS = None
    metrics._PROM_NODE_DURATION = None

    # Prometheus global registry
    _unregister_prom_collectors()

    yield

    # ── After test ──
    bootstrap._TRACER_INITIALIZED = False
    metrics._initialized = False
    metrics._meter = None
    metrics._PROM_LLM_ERRORS = None
    metrics._PROM_NODE_DURATION = None
    _unregister_prom_collectors()
