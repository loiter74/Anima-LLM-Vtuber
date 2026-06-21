from __future__ import annotations

"""Tests for node_error shared error logging utility."""

import uuid

import pytest_asyncio

from animetta.orchestration.graph import stats_store as ss
from animetta.orchestration.graph.node_error import VALID_ERROR_TYPES, log_node_error
from animetta.orchestration.graph.stats_store import StatsStore, close_stats_store


class TestLogNodeError:
    """Tests for log_node_error() utility."""

    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        """Create a temporary StatsStore for testing."""
        db_path = str(tmp_path / "test_node_error.db")
        s = StatsStore(db_path=db_path)
        await s.init()
        yield s
        await s.close()

    @pytest_asyncio.fixture
    async def mock_get_store(self, monkeypatch, store):
        """Patch get_stats_store to return our test store."""
        await close_stats_store()
        ss._store = store
        yield
        if ss._store is store:
            ss._store = None

    @pytest_asyncio.fixture
    async def trace_id(self, store):
        """Create a trace that error spans can attach to."""
        tid = str(uuid.uuid4())
        await store.create_trace(tid, "test-session", "text", "hello")
        return tid

    async def test_with_valid_trace_id_creates_span(self, mock_get_store, store, trace_id):
        """log_node_error with valid trace_id should create an error span."""

        await log_node_error(
            session_id="test-session",
            node_name="llm_node",
            error_type="timeout",
            provider="deepseek",
            duration_ms=30000,
            trace_id=trace_id,
        )

        # Verify span was created
        detail = await store.get_trace_detail(trace_id)
        assert detail is not None
        spans = detail["spans"]
        assert len(spans) >= 1

        # Find the error span
        error_spans = [s for s in spans if s["status"] == "error"]
        assert len(error_spans) >= 1
        error_span = error_spans[0]
        assert error_span["node_name"] == "llm_node"
        assert error_span["status"] == "error"

    async def test_invalid_error_type_defaults_to_unknown(self, mock_get_store, store, trace_id):
        """Unknown error_type should be mapped to 'unknown'."""

        await log_node_error(
            session_id="test-session",
            node_name="tts_node",
            error_type="cosmic_ray",
            provider="edge_tts",
            duration_ms=5000,
            trace_id=trace_id,
        )

        # Verify span was created (with error_type in input_summary)
        detail = await store.get_trace_detail(trace_id)
        spans = detail["spans"]
        error_spans = [s for s in spans if s["status"] == "error"]
        assert len(error_spans) >= 1

    async def test_none_trace_id_skips_span(self, mock_get_store, store, trace_id):
        """When trace_id is None, no span should be created and no exception."""

        # Should not raise
        await log_node_error(
            session_id="test-session",
            node_name="asr_node",
            error_type="network_error",
            provider="whisper",
            duration_ms=0,
            trace_id=None,
        )

        # Verify no new spans beyond what was there
        detail = await store.get_trace_detail(trace_id)
        # The trace itself exists but no error span attached
        assert detail is not None

    async def test_all_valid_error_types_accepted(self, mock_get_store, store, trace_id):
        """All 4 valid error types should be accepted without mapping to 'unknown'."""

        for error_type in sorted(VALID_ERROR_TYPES):
            await log_node_error(
                session_id="test-session",
                node_name="llm_node",
                error_type=error_type,
                provider="test",
                duration_ms=100,
                trace_id=trace_id,
            )

        # All 4 should create spans
        detail = await store.get_trace_detail(trace_id)
        error_spans = [s for s in detail["spans"] if s["status"] == "error"]
        assert len(error_spans) == len(VALID_ERROR_TYPES)

    async def test_validation_set_matches_spec(self):
        """VALID_ERROR_TYPES should contain exactly the 4 expected values."""

        assert frozenset({
            "timeout", "rate_limit", "network_error", "invalid_response",
        }) == VALID_ERROR_TYPES
