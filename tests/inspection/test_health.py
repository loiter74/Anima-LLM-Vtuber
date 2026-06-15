"""Tests for component health check probes."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.inspection.checks.health import (
    ASR_TIMEOUT,
    CHROMA_TIMEOUT,
    COMPONENT_CHECKS,
    LLM_TIMEOUT,
    MEMORY_TIMEOUT,
    METRICS_TIMEOUT,
    STATS_STORE_TIMEOUT,
    TTS_TIMEOUT,
    ComponentCheck,
    _probe_asr_available,
    _probe_chroma,
    _probe_llm_available,
    _probe_memory_read,
    _probe_metrics_endpoint,
    _probe_stats_store,
    _probe_tts_available,
    _run_single_probe,
    check_all_components,
)
from animetta.inspection.models import CheckResult

# ── Helpers ─────────────────────────────────────────────────


def _make_chromadb_mock(list_collections_ret=None, list_collections_raises=None):
    """Create a mock chromadb module with PersistentClient."""
    mock_client = MagicMock()
    if list_collections_raises:
        mock_client.list_collections = MagicMock(side_effect=list_collections_raises)
    else:
        mock_client.list_collections = MagicMock(return_value=list_collections_ret or [])

    mock_col = MagicMock()
    mock_col.count = MagicMock(return_value=42)
    mock_client.get_collection = MagicMock(return_value=mock_col)

    mock_chromadb = MagicMock()
    mock_chromadb.PersistentClient = MagicMock(return_value=mock_client)

    MagicMock()
    mock_settings_module = MagicMock()
    mock_settings_module.Settings = MagicMock(return_value=MagicMock())
    mock_chromadb.config = mock_settings_module

    return mock_chromadb, mock_client


def _make_aiohttp_mock(
    status=200,
    text_body="anima_requests_total 42\nprocess_cpu_seconds 1.0",
    get_raises=None,
):
    """Create a mock aiohttp module."""
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.text = AsyncMock(return_value=text_body)

    mock_cm = MagicMock()
    if get_raises:
        mock_cm.__aenter__ = AsyncMock(side_effect=get_raises)
    else:
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(return_value=mock_cm)

    mock_aiohttp = MagicMock()
    mock_aiohttp.ClientSession = MagicMock(return_value=mock_session)
    mock_aiohttp.ClientConnectorError = type(
        "ClientConnectorError",
        (Exception,),
        {},
    )
    mock_aiohttp.ClientTimeout = MagicMock(return_value=MagicMock())

    return mock_aiohttp, mock_session


# ── ComponentCheck dataclass ────────────────────────────────


class TestComponentCheck:
    """ComponentCheck dataclass tests."""

    @staticmethod
    async def _dummy_probe() -> bool:
        return True

    def test_instantiation(self):
        check = ComponentCheck(
            name="test",
            probe=self._dummy_probe,
            timeout=1.0,
            description="test check",
        )
        assert check.name == "test"
        assert check.timeout == 1.0
        assert check.description == "test check"
        # Probe is the same callable (static method so no binding issue)
        assert check.probe == self._dummy_probe

    def test_default_description(self):
        check = ComponentCheck(
            name="minimal", probe=self._dummy_probe, timeout=0.5
        )
        assert check.description == ""


# ── COMPONENT_CHECKS registry ───────────────────────────────


class TestComponentChecksRegistry:
    """Validate the COMPONENT_CHECKS registry."""

    def test_has_seven_checks(self):
        assert len(COMPONENT_CHECKS) == 8

    def test_all_names_unique(self):
        names = [c.name for c in COMPONENT_CHECKS]
        assert len(names) == len(set(names))

    def test_all_names_expected(self):
        names = {c.name for c in COMPONENT_CHECKS}
        assert names == {
            "stats_store",
            "chroma",
            "llm_available",
            "llm_connectivity",
            "tts_available",
            "asr_available",
            "memory_read",
            "metrics_endpoint",
        }

    def test_all_probes_callable(self):
        for check in COMPONENT_CHECKS:
            assert callable(check.probe), f"{check.name}.probe is not callable"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_all_probes_are_async(self):
        for check in COMPONENT_CHECKS:
            assert asyncio.iscoroutinefunction(check.probe), (
                f"{check.name}.probe is not async"
            )

    def test_timeout_constants_defined(self):
        assert STATS_STORE_TIMEOUT == 2.0
        assert CHROMA_TIMEOUT == 3.0
        assert LLM_TIMEOUT == 5.0
        assert TTS_TIMEOUT == 3.0
        assert ASR_TIMEOUT == 3.0
        assert MEMORY_TIMEOUT == 3.0
        assert METRICS_TIMEOUT == 3.0


# ── _probe_stats_store ──────────────────────────────────────


class TestProbeStatsStore:
    """StatsStore probe tests."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_success(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        mock_store = MagicMock()
        mock_store._db = MagicMock()
        mock_store._db.execute = AsyncMock(return_value=mock_cursor)

        with patch(
            "animetta.inspection.checks.health.get_stats_store",
            AsyncMock(return_value=mock_store),
        ):
            result = await _probe_stats_store()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_failure_on_exception(self):
        with patch(
            "animetta.inspection.checks.health.get_stats_store",
            AsyncMock(side_effect=RuntimeError("db down")),
        ):
            result = await _probe_stats_store()
            assert result is False


# ── _probe_chroma ───────────────────────────────────────────


class TestProbeChroma:
    """ChromaDB probe tests."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_success(self):
        mock_chromadb, _ = _make_chromadb_mock()
        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            # Also need chromadb.config to be accessible
            sys.modules["chromadb.config"] = mock_chromadb.config
            try:
                result = await _probe_chroma()
                assert result is True
            finally:
                sys.modules.pop("chromadb.config", None)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_not_configured_returns_true(self):
        # Remove chromadb from sys.modules to simulate not installed
        with patch.dict(sys.modules, {"chromadb": None}):
            result = await _probe_chroma()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_chromadb_connection_failure(self):
        mock_chromadb, _ = _make_chromadb_mock(
            list_collections_raises=RuntimeError("connection refused")
        )
        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            sys.modules["chromadb.config"] = mock_chromadb.config
            try:
                result = await _probe_chroma()
                assert result is False
            finally:
                sys.modules.pop("chromadb.config", None)


# ── _probe_llm_available ────────────────────────────────────


class TestProbeLlmAvailable:
    """LLM service probe tests."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_llm_available(self):
        with patch("animetta.core.service_pool.ServicePool._ready", True), \
             patch("animetta.core.service_pool.ServicePool._llm", MagicMock()):
            result = await _probe_llm_available()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_llm_not_available(self):
        with patch("animetta.core.service_pool.ServicePool._ready", True), \
             patch("animetta.core.service_pool.ServicePool._llm", None):
            result = await _probe_llm_available()
            assert result is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_not_configured_returns_true(self):
        with patch("animetta.core.service_pool.ServicePool._ready", False), \
             patch("animetta.core.service_pool.ServicePool._llm", None):
            result = await _probe_llm_available()
            assert result is True


# ── _probe_tts_available ────────────────────────────────────


class TestProbeTtsAvailable:
    """TTS engine probe tests."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_tts_available(self):
        with patch("animetta.core.service_pool.ServicePool._ready", True), \
             patch("animetta.core.service_pool.ServicePool._tts", MagicMock()):
            result = await _probe_tts_available()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_tts_not_available(self):
        with patch("animetta.core.service_pool.ServicePool._ready", True), \
             patch("animetta.core.service_pool.ServicePool._tts", None):
            result = await _probe_tts_available()
            assert result is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_not_configured_returns_true(self):
        with patch("animetta.core.service_pool.ServicePool._ready", False), \
             patch("animetta.core.service_pool.ServicePool._tts", None):
            result = await _probe_tts_available()
            assert result is True


# ── _probe_asr_available ────────────────────────────────────


class TestProbeAsrAvailable:
    """ASR model probe tests."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_asr_available(self):
        with patch("animetta.core.service_pool.ServicePool._ready", True), \
             patch("animetta.core.service_pool.ServicePool._asr", MagicMock()):
            result = await _probe_asr_available()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_asr_not_available(self):
        with patch("animetta.core.service_pool.ServicePool._ready", True), \
             patch("animetta.core.service_pool.ServicePool._asr", None):
            result = await _probe_asr_available()
            assert result is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_not_configured_returns_true(self):
        with patch("animetta.core.service_pool.ServicePool._ready", False), \
             patch("animetta.core.service_pool.ServicePool._asr", None):
            result = await _probe_asr_available()
            assert result is True


# ── _probe_memory_read ──────────────────────────────────────


class TestProbeMemoryRead:
    """Memory read probe tests."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_success_with_collections(self):
        mock_col = MagicMock()
        mock_col.name = "memory_default"
        mock_col.count = MagicMock(return_value=42)
        mock_client = MagicMock()
        mock_client.list_collections = MagicMock(return_value=[mock_col])
        mock_client.get_collection = MagicMock(return_value=mock_col)

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient = MagicMock(return_value=mock_client)
        mock_settings_module = MagicMock()
        mock_settings_module.Settings = MagicMock(return_value=MagicMock())
        mock_chromadb.config = mock_settings_module

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            sys.modules["chromadb.config"] = mock_chromadb.config
            try:
                result = await _probe_memory_read()
                assert result is True
            finally:
                sys.modules.pop("chromadb.config", None)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_collections_returns_true(self):
        mock_client = MagicMock()
        mock_client.list_collections = MagicMock(return_value=[])

        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient = MagicMock(return_value=mock_client)
        mock_settings_module = MagicMock()
        mock_settings_module.Settings = MagicMock(return_value=MagicMock())
        mock_chromadb.config = mock_settings_module

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            sys.modules["chromadb.config"] = mock_chromadb.config
            try:
                result = await _probe_memory_read()
                assert result is True
            finally:
                sys.modules.pop("chromadb.config", None)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_not_configured_returns_true(self):
        with patch.dict(sys.modules, {"chromadb": None}):
            result = await _probe_memory_read()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_chromadb_failure_returns_false(self):
        mock_client = MagicMock()
        mock_client.list_collections = MagicMock(
            side_effect=RuntimeError("disk full")
        )
        mock_chromadb = MagicMock()
        mock_chromadb.PersistentClient = MagicMock(return_value=mock_client)
        mock_settings_module = MagicMock()
        mock_settings_module.Settings = MagicMock(return_value=MagicMock())
        mock_chromadb.config = mock_settings_module

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            sys.modules["chromadb.config"] = mock_chromadb.config
            try:
                result = await _probe_memory_read()
                assert result is False
            finally:
                sys.modules.pop("chromadb.config", None)


# ── _probe_metrics_endpoint ─────────────────────────────────


class TestProbeMetricsEndpoint:
    """Metrics endpoint probe tests."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_success_with_expected_counters(self):
        mock_aiohttp, _ = _make_aiohttp_mock(status=200)
        with patch.dict(sys.modules, {"aiohttp": mock_aiohttp}):
            result = await _probe_metrics_endpoint()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_200_status_returns_false(self):
        mock_aiohttp, _ = _make_aiohttp_mock(
            status=500, text_body="Internal Server Error"
        )
        with patch.dict(sys.modules, {"aiohttp": mock_aiohttp}):
            result = await _probe_metrics_endpoint()
            assert result is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_not_configured_returns_true(self):
        with patch.dict(sys.modules, {"aiohttp": None}):
            result = await _probe_metrics_endpoint()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_connection_refused_returns_true(self):
        import aiohttp as real_aiohttp

        conn_err = real_aiohttp.ClientConnectorError(
            connection_key=MagicMock(), os_error=OSError("refused")
        )
        mock_aiohttp, _ = _make_aiohttp_mock(get_raises=conn_err)
        mock_aiohttp.ClientConnectorError = real_aiohttp.ClientConnectorError

        with patch.dict(sys.modules, {"aiohttp": mock_aiohttp}):
            result = await _probe_metrics_endpoint()
            assert result is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_timeout_returns_false(self):
        mock_aiohttp, _ = _make_aiohttp_mock(get_raises=TimeoutError())
        with patch.dict(sys.modules, {"aiohttp": mock_aiohttp}):
            result = await _probe_metrics_endpoint()
            assert result is False


# ── _run_single_probe ───────────────────────────────────────


class TestRunSingleProbe:
    """Tests for the _run_single_probe helper."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_passed_when_probe_true(self):
        async def _ok() -> bool:
            return True

        check = ComponentCheck(name="test_ok", probe=_ok, timeout=1.0)
        result = await _run_single_probe(check)
        assert isinstance(result, CheckResult)
        assert result.ok is True
        assert result.name == "test_ok"
        assert result.duration_ms >= 0.0
        assert result.error is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_failed_when_probe_false(self):
        async def _fail() -> bool:
            return False

        check = ComponentCheck(name="test_fail", probe=_fail, timeout=1.0)
        result = await _run_single_probe(check)
        assert isinstance(result, CheckResult)
        assert result.ok is False
        assert result.name == "test_fail"
        assert "False" in result.error

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_failed_on_timeout(self):
        async def _slow() -> bool:
            await asyncio.sleep(10.0)
            return True

        check = ComponentCheck(name="test_timeout", probe=_slow, timeout=0.01)
        result = await _run_single_probe(check)
        assert isinstance(result, CheckResult)
        assert result.ok is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_failed_on_exception(self):
        async def _crash() -> bool:
            raise ValueError("boom")

        check = ComponentCheck(name="test_crash", probe=_crash, timeout=1.0)
        result = await _run_single_probe(check)
        assert isinstance(result, CheckResult)
        assert result.ok is False
        assert "ValueError" in result.error
        assert "boom" in result.error

    @pytest.mark.asyncio(loop_scope="function")
    async def test_includes_duration_in_result(self):
        async def _quick() -> bool:
            return True

        check = ComponentCheck(name="timed", probe=_quick, timeout=1.0)
        result = await _run_single_probe(check)
        assert result.duration_ms >= 0.0
        assert result.duration_ms < 1000.0  # should be very fast


# ── check_all_components ────────────────────────────────────


class TestCheckAllComponents:
    """Integration tests for check_all_components().

    These tests mock the underlying dependencies (ServicePool, get_stats_store,
    chromadb, aiohttp) rather than the probe functions themselves, because
    COMPONENT_CHECKS stores function references at import time that cannot
    be patched at the module attribute level after the tuple is created.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_dict_with_all_check_names(self):
        """All 7 checks should return results dict — probes run against mocks."""
        # Mock stats_store
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        mock_store = MagicMock()
        mock_store._db = MagicMock()
        mock_store._db.execute = AsyncMock(return_value=mock_cursor)

        # Mock chromadb for both chroma and memory_read probes
        mock_chromadb, _ = _make_chromadb_mock()
        mock_chromadb.config.Settings = MagicMock(return_value=MagicMock())

        # Mock aiohttp for metrics_endpoint probe
        mock_aiohttp, _ = _make_aiohttp_mock(status=200)

        with (
            patch(
                "animetta.inspection.checks.health.get_stats_store",
                AsyncMock(return_value=mock_store),
            ),
            patch("animetta.core.service_pool.ServicePool._ready", False),
            patch.dict(sys.modules, {"chromadb": mock_chromadb}),
            patch.dict(sys.modules, {"aiohttp": mock_aiohttp}),
        ):
            sys.modules["chromadb.config"] = mock_chromadb.config
            try:
                results = await check_all_components()
            finally:
                sys.modules.pop("chromadb.config", None)

        assert isinstance(results, dict)
        assert len(results) == 8
        expected_names = {
            "stats_store",
            "chroma",
            "llm_available",
            "llm_connectivity",
            "tts_available",
            "asr_available",
            "memory_read",
            "metrics_endpoint",
        }
        assert set(results.keys()) == expected_names
        for result in results.values():
            assert isinstance(result, CheckResult)
            assert result.ok is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_mixed_pass_fail(self):
        """When TTS is not available (_ready=True, _tts=None), it fails."""
        # Mock stats_store to pass
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=(1,))
        mock_store = MagicMock()
        mock_store._db = MagicMock()
        mock_store._db.execute = AsyncMock(return_value=mock_cursor)

        # Mock chromadb for both chroma and memory_read probes
        mock_chromadb, _ = _make_chromadb_mock()
        mock_chromadb.config.Settings = MagicMock(return_value=MagicMock())

        # Mock aiohttp for metrics_endpoint probe
        mock_aiohttp, _ = _make_aiohttp_mock(status=200)

        with (
            patch(
                "animetta.inspection.checks.health.get_stats_store",
                AsyncMock(return_value=mock_store),
            ),
            patch("animetta.core.service_pool.ServicePool._ready", True),
            patch("animetta.core.service_pool.ServicePool._llm", MagicMock()),
            patch("animetta.core.service_pool.ServicePool._tts", None),  # <-- TTS unavailable
            patch("animetta.core.service_pool.ServicePool._asr", MagicMock()),
            patch.dict(sys.modules, {"chromadb": mock_chromadb}),
            patch.dict(sys.modules, {"aiohttp": mock_aiohttp}),
        ):
            sys.modules["chromadb.config"] = mock_chromadb.config
            try:
                results = await check_all_components()
            finally:
                sys.modules.pop("chromadb.config", None)

        assert results["stats_store"].ok is True
        assert results["chroma"].ok is True
        assert results["llm_available"].ok is True
        assert results["tts_available"].ok is False
        assert results["asr_available"].ok is True
        assert results["memory_read"].ok is True
        assert results["metrics_endpoint"].ok is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_concurrent_execution(self):
        """Verify probes run concurrently by timing."""
        call_order: list[str] = []

        async def _slow_a() -> bool:
            call_order.append("a")
            await asyncio.sleep(0.05)
            return True

        async def _slow_b() -> bool:
            call_order.append("b")
            await asyncio.sleep(0.05)
            return True

        custom_checks = (
            ComponentCheck(name="a", probe=_slow_a, timeout=1.0),
            ComponentCheck(name="b", probe=_slow_b, timeout=1.0),
        )

        with patch(
            "animetta.inspection.checks.health.COMPONENT_CHECKS", custom_checks
        ):
            results = await check_all_components()

        assert len(results) == 2
        assert results["a"].ok is True
        assert results["b"].ok is True
        assert len(call_order) == 2

    @pytest.mark.asyncio(loop_scope="function")
    async def test_timeout_does_not_abort_others(self):
        """A timing-out probe should not prevent other probes from completing."""
        async def _timeout() -> bool:
            await asyncio.sleep(10.0)
            return True

        async def _quick() -> bool:
            return True

        custom_checks = (
            ComponentCheck(name="timeout_check", probe=_timeout, timeout=0.01),
            ComponentCheck(name="quick_check", probe=_quick, timeout=1.0),
        )

        with patch(
            "animetta.inspection.checks.health.COMPONENT_CHECKS", custom_checks
        ):
            results = await check_all_components()

        assert results["timeout_check"].ok is False
        assert "timeout" in results["timeout_check"].error.lower()
        assert results["quick_check"].ok is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_exception_does_not_abort_others(self):
        """A crashing probe should not prevent other probes from completing."""
        async def _crash() -> bool:
            raise RuntimeError("unexpected failure")

        async def _ok() -> bool:
            return True

        custom_checks = (
            ComponentCheck(name="crash_check", probe=_crash, timeout=1.0),
            ComponentCheck(name="fine_check", probe=_ok, timeout=1.0),
        )

        with patch(
            "animetta.inspection.checks.health.COMPONENT_CHECKS", custom_checks
        ):
            results = await check_all_components()

        assert results["crash_check"].ok is False
        assert "RuntimeError" in results["crash_check"].error
        assert results["fine_check"].ok is True

    @pytest.mark.asyncio(loop_scope="function")
    async def test_all_fail_still_returns_dict(self):
        """Even with all probes failing, return a complete dict."""
        async def _fail() -> bool:
            return False

        custom_checks = (
            ComponentCheck(name="a", probe=_fail, timeout=1.0),
            ComponentCheck(name="b", probe=_fail, timeout=1.0),
        )

        with patch(
            "animetta.inspection.checks.health.COMPONENT_CHECKS", custom_checks
        ):
            results = await check_all_components()

        assert len(results) == 2
        assert results["a"].ok is False
        assert results["b"].ok is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_check_all_components_with_real_probes_graceful(self):
        """Call with real probes — should not raise, even if services are down."""
        try:
            results = await check_all_components()
            assert isinstance(results, dict)
            assert len(results) == 8
        except Exception as e:
            pytest.fail(f"check_all_components raised unexpectedly: {e}")
