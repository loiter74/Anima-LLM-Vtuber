from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src" / "animetta"


def test_legacy_trace_writers_are_removed() -> None:
    removed = (
        SRC / "orchestration" / "graph" / "stats_store.py",
        SRC / "orchestration" / "graph" / "stats_handler.py",
        SRC / "tracing" / "exporter.py",
        SRC / "tracing" / "metrics.py",
    )
    assert all(not path.exists() for path in removed)


def test_runtime_has_one_canonical_trace_writer() -> None:
    python = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SRC.rglob("*.py")
        if "tools/minecraft" not in path.as_posix()
    )
    assert "INSERT INTO observation_traces" in python
    assert python.count("INSERT INTO observation_traces") == 1
    assert "INSERT INTO traces" not in python
    assert "get_stats_store" not in python
    assert "StatsCallbackHandler" not in python
    assert "StatsSpanExporter" not in python


def test_inspection_has_no_private_database_or_parallel_chroma_probe() -> None:
    inspection = "\n".join(
        path.read_text(encoding="utf-8") for path in (SRC / "inspection").rglob("*.py")
    )
    assert "._db" not in inspection
    assert "PersistentClient" not in inspection
    assert ".myagent" not in inspection


def test_business_modules_have_no_direct_prometheus_updates() -> None:
    business_roots = (
        SRC / "orchestration",
        SRC / "services",
        SRC / "memory",
    )
    business = "\n".join(
        path.read_text(encoding="utf-8")
        for root in business_roots
        for path in root.rglob("*.py")
        if "tools/minecraft" not in path.as_posix()
        and path != SRC / "orchestration" / "server" / "websocket.py"
    )
    assert "prometheus_client" not in business
    assert "tracing.metrics" not in business


def test_dashboard_has_no_fixed_legacy_node_topology() -> None:
    dashboard = (ROOT / "frontend" / "src" / "views" / "DashboardPage.vue").read_text(
        encoding="utf-8"
    )
    assert "const topology =" not in dashboard
    assert "conversation_turn" not in dashboard
    assert ".spans" not in dashboard
