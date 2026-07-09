from __future__ import annotations

"""Tests for stats API endpoints — health check, overview, nodes, traces."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from animetta.inspection.models import CheckResult
from animetta.orchestration.server.stats_api import _get_gpu_info, get_stats_routes

# ── Helpers ────────────────────────────────────────────────────────


def _build_test_app(store_mock=None):
    """Build a Starlette app with the stats routes and optional mocked store."""
    routes = get_stats_routes()
    app = Starlette(routes=routes)
    return app


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def mock_store():
    """Mock StatsStore with async methods returning canned data."""
    store = MagicMock()
    store.get_overview = AsyncMock(return_value={
        "total_sessions": 10,
        "total_messages": 100,
        "avg_latency_ms": 250.0,
    })
    store.get_node_stats = AsyncMock(return_value={
        "llm_node": {"calls": 50, "avg_duration_ms": 300},
        "tts_node": {"calls": 30, "avg_duration_ms": 150},
    })
    store.get_recent_traces = AsyncMock(return_value=[
        {"trace_id": "abc", "status": "ok", "total_duration_ms": 500},
        {"trace_id": "def", "status": "ok", "total_duration_ms": 300},
    ])
    store.get_trace_detail = AsyncMock(return_value={
        "trace_id": "abc",
        "status": "ok",
        "total_duration_ms": 500,
        "conversation_turn": {
            "trace_id": "abc",
            "session_id": "desktop",
            "input_type": "text",
            "user_text": "full user text",
            "assistant_text": "full assistant text",
            "status": "ok",
            "error_msg": None,
            "metadata": {"source": "test"},
            "created_at": "2026-07-09T10:00:00",
        },
        "spans": [
            {"span_id": "s1", "parent_span_id": None, "name": "llm_call"},
            {"span_id": "s2", "parent_span_id": "s1", "name": "tts_call"},
        ],
    })
    store.get_latest_inspection_report = AsyncMock(return_value={
        "run_id": "inspection-1",
        "started_at": 1000.0,
        "finished_at": 1001.0,
        "overall_ok": True,
        "checks": {
            "stats_store": {"name": "stats_store", "ok": True},
        },
        "created_at": 1001.5,
    })
    return store


@pytest.fixture
def client(mock_store):
    """TestClient with mocked stats store."""
    with patch("animetta.orchestration.server.stats_api.get_stats_store",
               AsyncMock(return_value=mock_store)):
        app = _build_test_app()
        with TestClient(app) as c:
            yield c


# ── Health Check ───────────────────────────────────────────────────


class TestHealthEndpoint:
    """GET /health"""

    def test_health_returns_ok(self, client):
        """Health check returns {"status": "ok"}."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "service" in data
        assert "timestamp" in data

    def test_health_has_service_field(self, client):
        """Health response includes service name."""
        resp = client.get("/health")
        data = resp.json()
        assert data["service"] == "anima"

    def test_health_returns_500_when_probe_runner_crashes(self):
        """Health check infrastructure failures must not look HTTP-healthy."""
        with patch(
            "animetta.orchestration.server.stats_api.check_all_components",
            AsyncMock(side_effect=RuntimeError("probe runner crashed")),
        ):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/health")

        assert resp.status_code == 500
        data = resp.json()
        assert data["status"] == "error"
        assert data["service"] == "anima"
        assert "probe runner crashed" in data["error"]

    def test_health_returns_503_when_component_check_fails(self):
        """A degraded health body must also be unhealthy at the HTTP layer."""
        with patch(
            "animetta.orchestration.server.stats_api.check_all_components",
            AsyncMock(
                return_value={
                    "llm_available": CheckResult.failed(
                        "llm_available",
                        error="probe returned False",
                    )
                }
            ),
        ):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/health")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["llm_available"]["ok"] is False

    def test_gpu_info_accepts_current_torch_total_memory_property(self, monkeypatch):
        """GPU probe handles torch device properties exposing total_memory."""
        mib = 1024 * 1024
        fake_torch = SimpleNamespace(
            cuda=SimpleNamespace(
                is_available=lambda: True,
                get_device_name=lambda index: "Test GPU",
                get_device_properties=lambda index: SimpleNamespace(total_memory=8 * mib),
                memory_reserved=lambda index: 2 * mib,
                memory_allocated=lambda index: 1 * mib,
            )
        )
        monkeypatch.setitem(sys.modules, "torch", fake_torch)

        assert _get_gpu_info() == {
            "available": True,
            "name": "Test GPU",
            "memory_total_mb": 8.0,
            "memory_used_mb": 1.0,
            "memory_free_mb": 6.0,
        }


# ── Stats Overview ─────────────────────────────────────────────────


class TestStatsOverview:
    """GET /api/stats/overview"""

    def test_overview_returns_stats(self, client, mock_store):
        """Overview returns data from get_overview()."""
        resp = client.get("/api/stats/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_sessions"] == 10
        assert data["total_messages"] == 100
        assert data["avg_latency_ms"] == 250.0

    def test_overview_calls_get_overview(self, client, mock_store):
        """The underlying store method is called."""
        client.get("/api/stats/overview")
        mock_store.get_overview.assert_called_once()

    def test_overview_returns_500_on_error(self):
        """Overview returns 500 when store raises."""
        failing_store = MagicMock()
        failing_store.get_overview = AsyncMock(side_effect=RuntimeError("db fail"))

        with patch("animetta.orchestration.server.stats_api.get_stats_store",
                   AsyncMock(return_value=failing_store)):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/api/stats/overview")
            assert resp.status_code == 500
            assert "error" in resp.json()


# ── Node Stats ─────────────────────────────────────────────────────


class TestStatsNodes:
    """GET /api/stats/nodes"""

    def test_nodes_returns_node_stats(self, client, mock_store):
        """Node stats endpoint returns data from get_node_stats()."""
        resp = client.get("/api/stats/nodes")
        assert resp.status_code == 200
        data = resp.json()
        assert "llm_node" in data
        assert data["llm_node"]["calls"] == 50

    def test_nodes_calls_get_node_stats(self, client, mock_store):
        """The underlying store method is called."""
        client.get("/api/stats/nodes")
        mock_store.get_node_stats.assert_called_once()


# ── Traces ─────────────────────────────────────────────────────────


class TestStatsTraces:
    """GET /api/stats/traces"""

    def test_traces_returns_list(self, client, mock_store):
        """Traces endpoint returns list of traces."""
        resp = client.get("/api/stats/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["trace_id"] == "abc"

    def test_traces_passes_limit_and_offset(self, client, mock_store):
        """Limit and offset query params are passed to store."""
        client.get("/api/stats/traces?limit=10&offset=5")
        mock_store.get_recent_traces.assert_called_once_with(10, 5)

    def test_traces_uses_default_pagination(self, client, mock_store):
        """Default limit=50, offset=0 when not specified."""
        client.get("/api/stats/traces")
        mock_store.get_recent_traces.assert_called_once_with(50, 0)

    def test_traces_returns_500_on_error(self):
        """Traces returns 500 when store raises."""
        failing_store = MagicMock()
        failing_store.get_recent_traces = AsyncMock(side_effect=RuntimeError("db fail"))

        with patch("animetta.orchestration.server.stats_api.get_stats_store",
                   AsyncMock(return_value=failing_store)):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/api/stats/traces")
            assert resp.status_code == 500
            assert "error" in resp.json()


# ── Trace Detail ───────────────────────────────────────────────────


class TestStatsTraceDetail:
    """GET /api/stats/traces/{trace_id}"""

    def test_trace_detail_returns_data(self, client, mock_store):
        """Trace detail endpoint returns trace info."""
        resp = client.get("/api/stats/traces/abc")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "abc"
        assert data["status"] == "ok"

    def test_trace_detail_404_when_not_found(self):
        """Missing trace returns 404."""
        store = MagicMock()
        store.get_trace_detail = AsyncMock(return_value=None)

        with patch("animetta.orchestration.server.stats_api.get_stats_store",
                   AsyncMock(return_value=store)):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/api/stats/traces/missing")
            assert resp.status_code == 404
            assert "error" in resp.json()


# ── Trace Tree ─────────────────────────────────────────────────────


class TestStatsTraceTree:
    """GET /api/stats/traces/{trace_id}/tree"""

    def test_trace_tree_returns_nested_tree(self, client, mock_store):
        """Trace tree returns spans with nested children."""
        resp = client.get("/api/stats/traces/abc/tree")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "abc"
        assert "tree" in data
        assert len(data["tree"]) == 1
        assert data["tree"][0]["span_id"] == "s1"
        assert len(data["tree"][0]["children"]) == 1
        assert data["tree"][0]["children"][0]["span_id"] == "s2"
        assert data["conversation_turn"]["user_text"] == "full user text"
        assert data["conversation_turn"]["assistant_text"] == "full assistant text"

    def test_trace_tree_returns_404_when_not_found(self):
        """Missing trace tree returns 404."""
        store = MagicMock()
        store.get_trace_detail = AsyncMock(return_value=None)

        with patch("animetta.orchestration.server.stats_api.get_stats_store",
                   AsyncMock(return_value=store)):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/api/stats/traces/missing/tree")
            assert resp.status_code == 404


# ── Inspection Latest ──────────────────────────────────────────────


class TestStatsInspectionLatest:
    """GET /api/stats/inspection/latest"""

    def test_inspection_latest_returns_latest_report(self, client, mock_store):
        """Inspection endpoint returns the latest persisted report."""
        resp = client.get("/api/stats/inspection/latest")

        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "inspection-1"
        assert data["overall_ok"] is True
        assert data["checks"]["stats_store"]["ok"] is True
        mock_store.get_latest_inspection_report.assert_called_once()

    def test_inspection_latest_returns_404_when_no_report(self):
        """Missing inspection reports return a stable 404 payload."""
        store = MagicMock()
        store.get_latest_inspection_report = AsyncMock(return_value=None)

        with patch(
            "animetta.orchestration.server.stats_api.get_stats_store",
            AsyncMock(return_value=store),
        ):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/api/stats/inspection/latest")

        assert resp.status_code == 404
        assert resp.json() == {"error": "No inspection reports yet"}

    def test_inspection_latest_returns_500_on_store_error(self):
        """Store failures are surfaced as HTTP 500."""
        store = MagicMock()
        store.get_latest_inspection_report = AsyncMock(
            side_effect=RuntimeError("db fail")
        )

        with patch(
            "animetta.orchestration.server.stats_api.get_stats_store",
            AsyncMock(return_value=store),
        ):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/api/stats/inspection/latest")

        assert resp.status_code == 500
        assert "db fail" in resp.json()["error"]


# ── Route Registration ─────────────────────────────────────────────


class TestRouteRegistration:
    """Route list construction."""

    def test_get_stats_routes_returns_all_routes(self):
        """get_stats_routes returns all expected routes."""
        routes = get_stats_routes()

        path_set = {r.path for r in routes if hasattr(r, "path")}
        assert "/health" in path_set
        assert "/api/stats/overview" in path_set
        assert "/api/stats/nodes" in path_set
        assert "/api/stats/traces" in path_set
        assert "/api/stats/traces/{trace_id}" in path_set
        assert "/api/stats/traces/{trace_id}/tree" in path_set
        assert "/api/stats/inspection/latest" in path_set
        assert "/stats" in path_set
