"""Tests for data consistency checks.

Covers:
  - has_trace_in_last / chroma_responds / log_file_stale probes
  - check_data_consistency() aggregation logic
  - Pass, fail, and edge cases — all mocked, no real connections.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.inspection.checks.consistency import (
    check_data_consistency,
    chroma_responds,
    has_trace_in_last,
    log_file_stale,
)

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _make_mock_store(trace_count: int = 0, raises: bool = False) -> MagicMock:
    """Build a mock StatsStore with a configurable traces query result."""
    store = MagicMock()
    if raises:
        store._db = None
    else:
        mock_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=[trace_count])
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        store._db = mock_db
    return store


def _make_mock_chroma(raises: bool = False) -> MagicMock:
    """Build a mock chromadb PersistentClient."""
    if raises:
        return MagicMock(side_effect=ConnectionError("chroma down"))
    instance = MagicMock()
    instance.list_collections = MagicMock(return_value=["col_a"])
    return MagicMock(return_value=instance)


# ─────────────────────────────────────────────────────────────
# has_trace_in_last
# ─────────────────────────────────────────────────────────────


class TestHasTraceInLast:
    """Probe: StatsStore trace recency."""

    @pytest.mark.asyncio
    async def test_has_recent_traces(self):

        mock_store = _make_mock_store(trace_count=3)
        with patch(
            "animetta.inspection.checks.consistency.get_stats_store",
            new=AsyncMock(return_value=mock_store),
        ):
            result = await has_trace_in_last(minutes=60)
            assert result is True

    @pytest.mark.asyncio
    async def test_no_recent_traces(self):

        mock_store = _make_mock_store(trace_count=0)
        with patch(
            "animetta.inspection.checks.consistency.get_stats_store",
            new=AsyncMock(return_value=mock_store),
        ):
            result = await has_trace_in_last(minutes=60)
            assert result is False

    @pytest.mark.asyncio
    async def test_db_not_initialized(self):

        mock_store = _make_mock_store(raises=True)
        with patch(
            "animetta.inspection.checks.consistency.get_stats_store",
            new=AsyncMock(return_value=mock_store),
        ):
            result = await has_trace_in_last(minutes=60)
            assert result is False

    @pytest.mark.asyncio
    async def test_get_stats_store_raises(self):

        with patch(
            "animetta.inspection.checks.consistency.get_stats_store",
            side_effect=RuntimeError("boom"),
        ):
            result = await has_trace_in_last(minutes=60)
            assert result is False


# ─────────────────────────────────────────────────────────────
# chroma_responds
# ─────────────────────────────────────────────────────────────


class TestChromaResponds:
    """Probe: ChromaDB reachability.

    chromadb is imported lazily inside chroma_responds(), so we patch
    the actual chromadb.PersistentClient in the chromadb namespace.
    """

    @pytest.mark.asyncio
    async def test_chroma_reachable(self):

        with patch("chromadb.PersistentClient", _make_mock_chroma(raises=False)):
            result = await chroma_responds()
            assert result is True

    @pytest.mark.asyncio
    async def test_chroma_unreachable_raises(self):

        with patch(
            "chromadb.PersistentClient",
            side_effect=ConnectionError("unreachable"),
        ):
            result = await chroma_responds()
            assert result is False

    @pytest.mark.asyncio
    async def test_chroma_unreachable_runtime_error(self):

        with patch(
            "chromadb.PersistentClient",
            side_effect=RuntimeError("chroma exploded"),
        ):
            result = await chroma_responds()
            assert result is False


# ─────────────────────────────────────────────────────────────
# log_file_stale
# ─────────────────────────────────────────────────────────────


class TestLogFileStale:
    """Probe: log file freshness."""

    def test_log_fresh(self):

        now = time.time()
        with patch.object(Path, "exists", return_value=True), patch.object(
            Path, "stat", return_value=MagicMock(st_mtime=now)
        ):
            result = log_file_stale(minutes=60)
            assert result is False

    def test_log_file_missing(self):

        with patch.object(Path, "exists", return_value=False):
            result = log_file_stale(minutes=60)
            assert result is True

    def test_log_file_stale(self):

        old_time = time.time() - 7200  # 2 hours ago
        with patch.object(Path, "exists", return_value=True), patch.object(
            Path, "stat", return_value=MagicMock(st_mtime=old_time)
        ):
            result = log_file_stale(minutes=60)
            assert result is True

    def test_log_file_boundary_fresh(self):

        recent = time.time() - 30  # 30 seconds ago — within 60 min window
        with patch.object(Path, "exists", return_value=True), patch.object(
            Path, "stat", return_value=MagicMock(st_mtime=recent)
        ):
            result = log_file_stale(minutes=60)
            assert result is False


# ─────────────────────────────────────────────────────────────
# check_data_consistency (aggregation)
# ─────────────────────────────────────────────────────────────


class TestCheckDataConsistency:
    """Aggregation: check_data_consistency()."""

    _STATS = "animetta.inspection.checks.consistency.get_stats_store"
    _CHROMA = "chromadb.PersistentClient"

    @pytest.mark.asyncio
    async def test_all_pass(self):

        mock_store = _make_mock_store(trace_count=5)
        mock_chroma = _make_mock_chroma(raises=False)
        now = time.time()

        ps = patch(self._STATS, new=AsyncMock(return_value=mock_store))
        pc = patch(self._CHROMA, mock_chroma)
        pe = patch.object(Path, "exists", return_value=True)
        pst = patch.object(Path, "stat", return_value=MagicMock(st_mtime=now))

        with ps, pc, pe, pst:
            result = await check_data_consistency()
        assert result.ok is True
        assert result.name == "data_consistency"
        assert result.error is None
        assert result.detail["stats_has_recent_trace"] is True
        assert result.detail["chroma_ok"] is True
        assert result.detail["log_file_stale"] is False
        assert result.detail["issues"] == []

    @pytest.mark.asyncio
    async def test_no_recent_trace_fails(self):

        mock_store = _make_mock_store(trace_count=0)
        mock_chroma = _make_mock_chroma(raises=False)
        now = time.time()

        with patch(self._STATS, new=AsyncMock(return_value=mock_store)), \
             patch(self._CHROMA, mock_chroma), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_mtime=now)):
            result = await check_data_consistency()
        assert result.ok is False
        assert "stats_no_recent_trace" in result.error

    @pytest.mark.asyncio
    async def test_chroma_unreachable_fails(self):

        mock_store = _make_mock_store(trace_count=5)
        now = time.time()

        with patch(self._STATS, new=AsyncMock(return_value=mock_store)), \
             patch(self._CHROMA, side_effect=ConnectionError("unreachable")), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_mtime=now)):
            result = await check_data_consistency()
        assert result.ok is False
        assert "chroma_unreachable" in result.error

    @pytest.mark.asyncio
    async def test_log_file_stale_fails(self):

        mock_store = _make_mock_store(trace_count=5)
        mock_chroma = _make_mock_chroma(raises=False)
        old_time = time.time() - 7200

        with patch(self._STATS, new=AsyncMock(return_value=mock_store)), \
             patch(self._CHROMA, mock_chroma), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_mtime=old_time)):
            result = await check_data_consistency()
        assert result.ok is False
        assert "log_file_stale" in result.error

    @pytest.mark.asyncio
    async def test_all_fail(self):

        mock_store = _make_mock_store(trace_count=0)
        old_time = time.time() - 7200

        with patch(self._STATS, new=AsyncMock(return_value=mock_store)), \
             patch(self._CHROMA, side_effect=ConnectionError("unreachable")), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_mtime=old_time)):
            result = await check_data_consistency()
        assert result.ok is False
        assert "stats_no_recent_trace" in result.error
        assert "chroma_unreachable" in result.error
        assert "log_file_stale" in result.error
        assert len(result.detail["issues"]) == 3

    @pytest.mark.asyncio
    async def test_duration_ms_positive(self):

        mock_store = _make_mock_store(trace_count=1)
        mock_chroma = _make_mock_chroma(raises=False)
        now = time.time()

        with patch(self._STATS, new=AsyncMock(return_value=mock_store)), \
             patch(self._CHROMA, mock_chroma), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=MagicMock(st_mtime=now)):
            result = await check_data_consistency()
        assert result.duration_ms > 0
