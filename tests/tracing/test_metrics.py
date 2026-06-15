from __future__ import annotations

"""Tests for metrics.py — OTel MeterProvider initialization and instruments."""

from unittest.mock import MagicMock, patch

import animetta.tracing.metrics as metrics_mod


class TestInitMetrics:
    """Metrics initialization creates all required instruments."""

    def test_init_creates_meter(self):
        """init_metrics returns a valid Meter and sets initialized flag."""

        # Reset module state
        metrics_mod._initialized = False
        metrics_mod._meter = None

        with patch.object(metrics_mod, "MeterProvider") as mock_mp:
            mock_provider = MagicMock()
            mock_meter = MagicMock()
            mock_provider.get_meter.return_value = mock_meter
            mock_mp.return_value = mock_provider

            meter = metrics_mod.init_metrics(service_name="test")

            assert meter is mock_meter
            assert metrics_mod._initialized is True

    def test_init_is_idempotent(self):
        """Calling init_metrics twice returns same meter without re-initializing."""

        metrics_mod._initialized = False
        metrics_mod._meter = None

        with patch.object(metrics_mod, "MeterProvider") as mock_mp:
            mock_provider = MagicMock()
            mock_meter = MagicMock()
            mock_provider.get_meter.return_value = mock_meter
            mock_mp.return_value = mock_provider

            meter1 = metrics_mod.init_metrics(service_name="test")
            meter2 = metrics_mod.init_metrics(service_name="test")

            assert meter1 is meter2
            # MeterProvider should only be created once
            mock_mp.assert_called_once()

    def test_all_instruments_created(self):
        """init_metrics creates all 17 instruments."""

        metrics_mod._initialized = False
        metrics_mod._meter = None

        with patch.object(metrics_mod, "MeterProvider") as mock_mp:
            mock_provider = MagicMock()
            mock_meter = MagicMock()
            mock_provider.get_meter.return_value = mock_meter
            mock_mp.return_value = mock_provider

            metrics_mod.init_metrics(service_name="test")

            # All instruments should be created on the meter
            create_calls = mock_meter.method_calls
            histogram_calls = [c for c in create_calls if "create_histogram" in str(c)]
            counter_calls = [c for c in create_calls if "create_counter" in str(c)]
            updown_calls = [c for c in create_calls if "create_up_down_counter" in str(c)]

            # 8 histograms + 8 counters + 1 up_down_counter = 17 total
            assert len(create_calls) == 17
            assert len(histogram_calls) == 8
            assert len(counter_calls) == 8
            assert len(updown_calls) == 1


class TestAccessors:
    """Accessor functions return instruments after init."""

    def test_get_node_duration_after_init(self):
        """get_node_duration returns Histogram after initialization."""

        metrics_mod._initialized = False
        metrics_mod._meter = None

        with patch.object(metrics_mod, "MeterProvider") as mock_mp:
            mock_provider = MagicMock()
            mock_meter = MagicMock()
            mock_histogram = MagicMock()
            mock_meter.create_histogram.return_value = mock_histogram
            mock_meter.create_counter.return_value = MagicMock()
            mock_meter.create_up_down_counter.return_value = MagicMock()
            mock_provider.get_meter.return_value = mock_meter
            mock_mp.return_value = mock_provider

            metrics_mod.init_metrics(service_name="test")
            result = metrics_mod.get_node_duration()

            assert result is not None

    def test_accessor_before_init_returns_none_safe(self):
        """Accessors before init return None/NoOp but don't crash."""

        metrics_mod._initialized = False
        metrics_mod._meter = None
        metrics_mod._NODE_DURATION = None

        result = metrics_mod.get_node_duration()
        assert result is None
