from __future__ import annotations

"""Tests for stats API endpoints — health check, overview, nodes, traces."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from animetta.orchestration.server.stats_api import (
    _get_gpu_info,
    get_stats_routes,
    set_component_readiness_cache,
    set_runtime_readiness_context,
)

# ── Helpers ────────────────────────────────────────────────────────


def _build_test_app(store_mock=None):
    """Build a Starlette app with an injected ObservationQuery."""
    routes = get_stats_routes()
    app = Starlette(routes=routes)
    if store_mock is not None:
        app.state.observation_query = store_mock
    return app


class TestLiveStatsEndpoints:
    def test_live_overview_projects_source_badges_and_core_metrics(self, client, mock_store):
        detail = dict(mock_store.trace_detail.return_value)
        detail["attributes"] = {
            "actor_role": "developer",
            "source": "developer_console",
            "live_session_id": "live-1",
            "audience": "livestream",
        }
        detail["operations"] = [
            {
                "operation_id": "tool-1",
                "name": "tool:search",
                "layer": "service",
                "status": "success",
                "provider": None,
                "attributes": {"tool_name": "search", "tool_source": "mcp"},
            },
            {
                "operation_id": "llm-1",
                "name": "llm.chat",
                "layer": "service",
                "status": "success",
                "provider": "openai",
                "attributes": {},
            },
        ]
        mock_store.trace_detail.return_value = detail

        response = client.get("/api/stats/live?limit=20")

        assert response.status_code == 200
        payload = response.json()
        assert payload["metrics"]["turn_count"] == 2
        assert payload["metrics"]["tool_calls"] == 2
        assert payload["metrics"]["tool_success_rate"] == 100.0
        assert payload["turns"][0]["actor_role"] == "developer"
        assert payload["turns"][0]["source"] == "developer_console"

    def test_live_turn_uses_deterministic_phase_labels(self, client, mock_store):
        detail = dict(mock_store.trace_detail.return_value)
        detail["attributes"] = {"live_session_id": "live-1"}
        detail["operations"] = [
            {
                "operation_id": "reasoner-1",
                "name": "reasoner",
                "layer": "workflow",
                "status": "success",
                "started_at": 10.0,
                "duration_ms": 25.0,
                "provider": None,
                "model": None,
                "error_summary": None,
                "attributes": {},
            },
            {
                "operation_id": "tool-1",
                "name": "tool:search",
                "layer": "service",
                "status": "success",
                "started_at": 10.1,
                "duration_ms": 40.0,
                "provider": None,
                "model": None,
                "error_summary": None,
                "attributes": {"tool_name": "search"},
            },
        ]
        mock_store.trace_detail.return_value = detail

        response = client.get("/api/stats/live/turns/abc")

        assert response.status_code == 200
        activities = response.json()["activities"]
        assert [item["label"] for item in activities] == ["模型规划", "决定并调用工具"]


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def mock_store():
    """Mock ObservationQuery with ledger-shaped responses."""
    store = MagicMock()
    store.overview = AsyncMock(
        return_value={
            "schema_version": 2,
            "total_requests": 10,
            "success_count": 8,
            "degraded_count": 1,
            "failed_count": 1,
            "success_rate": 80.0,
            "avg_duration_ms": 250.0,
        }
    )
    store.operation_aggregates = AsyncMock(
        return_value=[
            {
                "layer": "workflow",
                "name": "llm_node",
                "operation_count": 50,
                "success_count": 49,
                "degraded_count": 0,
                "failure_count": 1,
                "avg_duration_ms": 300.0,
            }
        ]
    )
    trace_summary = {
        "message_id": "message-1",
        "conversation_id": "conversation-1",
        "session_id": "desktop",
        "runtime_profile": "development",
        "input_type": "text",
        "privacy_mode": "full",
        "started_at": 10.0,
        "finished_at": 10.5,
        "duration_ms": 500.0,
        "outcome": "success",
        "error_type": None,
    }
    store.recent_traces = AsyncMock(
        return_value=[
            {"trace_id": "abc", **trace_summary},
            {"trace_id": "def", **trace_summary},
        ]
    )
    store.trace_detail = AsyncMock(
        return_value={
            "trace_id": "abc",
            **trace_summary,
            "error_summary": None,
            "user_text": "full user text",
            "user_character_count": 14,
            "user_byte_count": 14,
            "user_digest": "u",
            "assistant_text": "full assistant text",
            "assistant_character_count": 19,
            "assistant_byte_count": 19,
            "assistant_digest": "a",
            "attributes": {},
            "operations": [],
            "operation_tree": [],
            "events": [],
            "post_turn": {"pending": 0, "completed": 0, "failed": 0, "operations": []},
            "schema_version": 2,
        }
    )
    store.inspection_reports = AsyncMock(
        return_value=[
            {
                "run_id": "inspection-1",
                "started_at": 1000.0,
                "finished_at": 1001.0,
                "overall_ok": True,
                "checks": {
                    "observation_ledger": {"name": "observation_ledger", "ok": True},
                },
                "created_at": 1001.5,
            }
        ]
    )
    return store


@pytest.fixture
def client(mock_store):
    """TestClient with mocked stats store."""
    app = _build_test_app(mock_store)
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

    def test_health_does_not_run_component_or_model_probes(self):
        """Liveness remains cheap even while readiness work is failing."""
        with patch(
            "animetta.orchestration.server.stats_api.ServicePool.get_readiness_snapshot",
            side_effect=RuntimeError("model readiness must not run"),
        ) as readiness:
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "anima"
        readiness.assert_not_called()

    def test_ready_returns_503_for_pending_preload(self):
        """Readiness is non-success while the real Qwen preload is pending."""
        snapshot = MagicMock()
        snapshot.to_dict.return_value = {
            "status": "not_ready",
            "ready": False,
            "profile": "golden",
            "acceptance_eligible": True,
            "components": {
                "tts": {"state": "loading", "ready": False, "reason": None},
            },
        }
        with patch(
            "animetta.orchestration.server.stats_api.ServicePool.get_readiness_snapshot",
            return_value=snapshot,
            create=True,
        ):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/ready")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "not_ready"
        assert data["components"]["tts"]["state"] == "loading"

    def test_ready_returns_200_for_complete_real_runtime(self):
        snapshot = MagicMock()
        snapshot.to_dict.return_value = {
            "status": "ready",
            "ready": True,
            "profile": "golden",
            "acceptance_eligible": True,
            "components": {},
        }
        with patch(
            "animetta.orchestration.server.stats_api.ServicePool.get_readiness_snapshot",
            return_value=snapshot,
            create=True,
        ):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/ready")

        assert resp.status_code == 200
        assert resp.json()["ready"] is True

    @pytest.mark.parametrize(
        "failed_component",
        ["observation_ledger", "memory_runtime", "metrics_projection"],
    )
    def test_ready_merges_cached_required_local_component_degradation(
        self,
        failed_component: str,
    ):
        snapshot = MagicMock()
        snapshot.to_dict.return_value = {
            "status": "ready",
            "ready": True,
            "profile": "production",
            "acceptance_eligible": True,
            "components": {},
        }
        components = {
            name: {
                "state": "failed" if name == failed_component else "ready",
                "ready": name != failed_component,
                "reason": "component_degraded" if name == failed_component else None,
            }
            for name in ("observation_ledger", "memory_runtime", "metrics_projection")
        }
        cache = SimpleNamespace(
            snapshot=lambda: {
                "ready": False,
                "components": components,
                "age_seconds": 0.1,
            }
        )
        config = SimpleNamespace(
            profile="production",
            observability=SimpleNamespace(
                enabled=True,
                prometheus=SimpleNamespace(enabled=True),
            ),
        )
        set_runtime_readiness_context(
            config,
            {"state": "ready", "ready": True, "reason": None},
        )
        set_component_readiness_cache(cache)
        try:
            with patch(
                "animetta.orchestration.server.stats_api.ServicePool.get_readiness_snapshot",
                return_value=snapshot,
            ):
                app = _build_test_app()
                with TestClient(app) as client:
                    response = client.get("/ready")
        finally:
            set_component_readiness_cache(None)

        assert response.status_code == 503
        payload = response.json()
        assert payload["ready"] is False
        assert payload["components"][failed_component]["ready"] is False

    def test_ready_fails_closed_and_redacts_snapshot_errors(self):
        with patch(
            "animetta.orchestration.server.stats_api.ServicePool.get_readiness_snapshot",
            side_effect=RuntimeError("https://user:password@example.invalid?api_key=secret"),
            create=True,
        ):
            app = _build_test_app()
            with TestClient(app) as c:
                resp = c.get("/ready")

        assert resp.status_code == 503
        assert resp.json() == {
            "status": "not_ready",
            "ready": False,
            "service": "anima",
            "reason": "snapshot_unavailable",
        }

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
        assert data["total_requests"] == 10
        assert data["degraded_count"] == 1
        assert data["avg_duration_ms"] == 250.0

    def test_overview_calls_get_overview(self, client, mock_store):
        """The underlying store method is called."""
        client.get("/api/stats/overview")
        mock_store.overview.assert_awaited_once()

    def test_overview_returns_500_on_error(self):
        """Overview returns 500 when store raises."""
        failing_store = MagicMock()
        failing_store.overview = AsyncMock(side_effect=RuntimeError("db fail"))
        app = _build_test_app(failing_store)
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
        assert data[0]["name"] == "llm_node"
        assert data[0]["operation_count"] == 50

    def test_nodes_calls_get_node_stats(self, client, mock_store):
        """The underlying store method is called."""
        client.get("/api/stats/nodes")
        mock_store.operation_aggregates.assert_awaited_once()


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
        mock_store.recent_traces.assert_awaited_once_with(10, 5)

    def test_traces_uses_default_pagination(self, client, mock_store):
        """Default limit=50, offset=0 when not specified."""
        client.get("/api/stats/traces")
        mock_store.recent_traces.assert_awaited_once_with(50, 0)

    def test_traces_returns_500_on_error(self):
        """Traces returns 500 when store raises."""
        failing_store = MagicMock()
        failing_store.recent_traces = AsyncMock(side_effect=RuntimeError("db fail"))
        app = _build_test_app(failing_store)
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
        assert data["outcome"] == "success"

    def test_trace_detail_404_when_not_found(self):
        """Missing trace returns 404."""
        store = MagicMock()
        store.trace_detail = AsyncMock(return_value=None)
        app = _build_test_app(store)
        with TestClient(app) as c:
            resp = c.get("/api/stats/traces/missing")
        assert resp.status_code == 404
        assert "error" in resp.json()


# ── Trace Tree ─────────────────────────────────────────────────────


class TestStatsTraceTree:
    """GET /api/stats/traces/{trace_id}/tree"""

    def test_trace_tree_returns_nested_tree(self, client, mock_store):
        """Trace tree returns the canonical operation hierarchy."""
        resp = client.get("/api/stats/traces/abc/tree")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "abc"
        assert data["operation_tree"] == []
        assert data["content"]["user"]["text"] == "full user text"
        assert data["content"]["assistant"]["text"] == "full assistant text"

    def test_trace_tree_returns_404_when_not_found(self):
        """Missing trace tree returns 404."""
        store = MagicMock()
        store.trace_detail = AsyncMock(return_value=None)
        app = _build_test_app(store)
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
        assert data["checks"]["observation_ledger"]["ok"] is True
        mock_store.inspection_reports.assert_awaited_once_with(1, 0)

    def test_inspection_latest_returns_404_when_no_report(self):
        """Missing inspection reports return a stable 404 payload."""
        store = MagicMock()
        store.inspection_reports = AsyncMock(return_value=[])
        app = _build_test_app(store)
        with TestClient(app) as c:
            resp = c.get("/api/stats/inspection/latest")

        assert resp.status_code == 404
        assert resp.json() == {"error": "No inspection reports yet"}

    def test_inspection_latest_returns_500_on_store_error(self):
        """Store failures are surfaced as HTTP 500."""
        store = MagicMock()
        store.inspection_reports = AsyncMock(side_effect=RuntimeError("db fail"))
        app = _build_test_app(store)
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
        assert "/ready" in path_set
        assert "/api/stats/overview" in path_set
        assert "/api/stats/nodes" in path_set
        assert "/api/stats/traces" in path_set
        assert "/api/stats/traces/{trace_id}" in path_set
        assert "/api/stats/traces/{trace_id}/tree" in path_set
        assert "/api/stats/inspection/latest" in path_set
        assert "/stats" not in path_set
