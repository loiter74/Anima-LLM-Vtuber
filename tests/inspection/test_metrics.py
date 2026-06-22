"""Tests for metrics pipeline self-check.

Covers:
  - GET /metrics endpoint reachability
  - Expected gauge/counter name verification
  - check_metrics_pipeline() aggregation
  - Pass, fail, and edge cases — all mocked, no real connections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from animetta.inspection.checks.metrics import check_metrics_pipeline

# ─────────────────────────────────────────────────────────────
# Test app factory
# ─────────────────────────────────────────────────────────────


def _make_metrics_app(body: str | None = None, status_code: int = 200) -> tuple:
    """Build a Starlette test app with a /metrics endpoint.

    Returns (Starlette app, httpx.ASGITransport).
    """
    if body is None:
        body = (
            "# HELP anima_llm_errors_total Total LLM errors\n"
            "# TYPE anima_llm_errors_total counter\n"
            "anima_llm_errors_total 0\n"
            "# HELP anima_node_duration_seconds Node duration histogram\n"
            "# TYPE anima_node_duration_seconds histogram\n"
        )

    async def metrics_view(request):
        return PlainTextResponse(body, status_code=status_code)

    app = Starlette(routes=[Route("/metrics", metrics_view)])
    return app, httpx.ASGITransport(app=app)


def _full_body() -> str:
    return (
        "# HELP anima_llm_errors_total Total LLM call errors\n"
        "# TYPE anima_llm_errors_total counter\n"
        "anima_llm_errors_total{provider=\"deepseek\"} 3\n"
        "# HELP anima_node_duration_seconds LangGraph node duration\n"
        "# TYPE anima_node_duration_seconds histogram\n"
        "anima_node_duration_seconds_bucket{node=\"llm\",le=\"0.5\"} 10\n"
        "anima_node_duration_seconds_bucket{node=\"llm\",le=\"1.0\"} 25\n"
        "anima_node_duration_seconds_bucket{node=\"llm\",le=\"+Inf\"} 30\n"
        "anima_node_duration_seconds_sum{node=\"llm\"} 22.5\n"
        "anima_node_duration_seconds_count{node=\"llm\"} 30\n"
    )


# ─────────────────────────────────────────────────────────────
# check_metrics_pipeline
# ─────────────────────────────────────────────────────────────


class TestCheckMetricsPipeline:
    """Aggregation: check_metrics_pipeline()."""

    @pytest.mark.asyncio
    async def test_all_pass(self):

        _, transport = _make_metrics_app(body=_full_body())
        mock_response = httpx.Response(200, text=_full_body(), request=MagicMock())

        mock_get = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_metrics_pipeline()
        assert result.ok is True
        assert result.name == "metrics_pipeline"
        assert result.error is None
        assert result.detail["status_code"] == 200
        assert result.detail["has_anima_llm_errors_total"] is True
        assert result.detail["has_anima_node_duration_seconds"] is True

    @pytest.mark.asyncio
    async def test_missing_expected_metric(self):

        # Body only has one of two required metrics
        body = (
            "# HELP anima_llm_errors_total Total LLM errors\n"
            "# TYPE anima_llm_errors_total counter\n"
            "anima_llm_errors_total 0\n"
        )
        mock_response = httpx.Response(200, text=body, request=MagicMock())
        mock_get = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_metrics_pipeline()
        assert result.ok is False
        assert "metrics_missing_anima_node_duration_seconds" in result.error
        assert result.detail["has_anima_llm_errors_total"] is True
        assert result.detail["has_anima_node_duration_seconds"] is False

    @pytest.mark.asyncio
    async def test_endpoint_unreachable(self):

        mock_get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_metrics_pipeline()
        assert result.ok is False
        assert "metrics_unreachable" in result.error

    @pytest.mark.asyncio
    async def test_endpoint_timeout(self):

        mock_get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_metrics_pipeline()
        assert result.ok is False
        assert "metrics_timeout" in result.error

    @pytest.mark.asyncio
    async def test_non_200_status(self):

        body = "Service Unavailable"
        mock_response = httpx.Response(503, text=body, request=MagicMock())
        mock_get = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_metrics_pipeline()
        assert result.ok is False
        assert "metrics_status_503" in result.error

    @pytest.mark.asyncio
    async def test_generic_exception(self):

        mock_get = AsyncMock(side_effect=RuntimeError("unexpected"))
        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_metrics_pipeline()
        assert result.ok is False
        assert "metrics_error" in result.error

    @pytest.mark.asyncio
    async def test_duration_ms_positive(self):

        mock_response = httpx.Response(200, text=_full_body(), request=MagicMock())
        mock_get = AsyncMock(return_value=mock_response)
        mock_client = MagicMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_metrics_pipeline()
        assert result.duration_ms > 0
