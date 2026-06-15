from __future__ import annotations

"""Tests for tracing bootstrap — init_tracing with and without OTLP.

Note: TracerProvider, Resource, SimpleSpanProcessor are imported inside
init_tracing(), not at module level. We patch at their source packages.
"""

from unittest.mock import MagicMock, patch

from animetta.tracing.bootstrap import init_tracing


class TestInitTracingDisabled:
    """When tracing is disabled, NoOpTracerProvider is used."""

    @patch("animetta.tracing.bootstrap._load_full_config")
    @patch("opentelemetry.trace.ProxyTracerProvider")
    def test_disabled_returns_noop(self, mock_proxy, mock_load):
        mock_load.return_value = {"tracing": {"enabled": False}}
        mock_proxy.return_value = MagicMock()

        init_tracing()

        mock_proxy.assert_called_once()

    @patch("animetta.tracing.bootstrap._load_full_config")
    @patch("opentelemetry.trace.ProxyTracerProvider")
    def test_disabled_override(self, mock_proxy, mock_load):
        mock_load.return_value = {"tracing": {"enabled": True}}
        mock_proxy.return_value = MagicMock()

        init_tracing(enabled=False)

        mock_proxy.assert_called_once()


class TestInitTracingBasic:
    """Basic tracing init without OTLP."""

    @patch("animetta.tracing.bootstrap._load_full_config")
    @patch("opentelemetry.sdk.resources.Resource")
    @patch("opentelemetry.sdk.trace.TracerProvider")
    @patch("opentelemetry.sdk.trace.export.SimpleSpanProcessor")
    @patch("animetta.tracing.exporter.StatsSpanExporter")
    def test_stats_exporter_always_added(
        self, mock_exp, mock_simple, mock_tp, mock_res, mock_load
    ):
        mock_load.return_value = {
            "tracing": {"enabled": True, "service_name": "test"},
            "otlp": {"enabled": False},
        }
        mock_provider = MagicMock()
        mock_tp.return_value = mock_provider

        with patch("animetta.tracing.metrics.init_metrics"):
            init_tracing()

        mock_exp.assert_called_once()
        mock_simple.assert_called_once()
        mock_provider.add_span_processor.assert_called()

    @patch("animetta.tracing.bootstrap._load_full_config")
    @patch("opentelemetry.sdk.trace.TracerProvider")
    def test_init_metrics_called(self, mock_tp, mock_load):
        mock_load.return_value = {
            "tracing": {"enabled": True, "service_name": "test"},
            "otlp": {"enabled": False},
        }
        mock_tp.return_value = MagicMock()

        with patch("opentelemetry.sdk.trace.export.SimpleSpanProcessor"), \
             patch("animetta.tracing.exporter.StatsSpanExporter"), \
             patch("opentelemetry.sdk.resources.Resource"), \
             patch("animetta.tracing.metrics.init_metrics") as mock_init:
            init_tracing()
            mock_init.assert_called_once()


class TestInitTracingOtlp:
    """OTLP dual-export when enabled."""

    @patch("animetta.tracing.bootstrap._load_full_config")
    @patch("opentelemetry.sdk.trace.TracerProvider")
    def test_otlp_disabled_skips(self, mock_tp, mock_load):
        mock_load.return_value = {
            "tracing": {"enabled": True, "service_name": "test"},
            "otlp": {"enabled": False},
        }
        mock_tp.return_value = MagicMock()

        with patch("opentelemetry.sdk.trace.export.SimpleSpanProcessor"), \
             patch("animetta.tracing.exporter.StatsSpanExporter"), \
             patch("opentelemetry.sdk.resources.Resource"), \
             patch("animetta.tracing.bootstrap._init_otlp_exporter") as mock_otlp, \
             patch("animetta.tracing.metrics.init_metrics"):
            init_tracing()
            mock_otlp.assert_not_called()

    @patch("animetta.tracing.bootstrap._load_full_config")
    @patch("opentelemetry.sdk.trace.TracerProvider")
    def test_otlp_enabled_calls_init(self, mock_tp, mock_load):
        mock_load.return_value = {
            "tracing": {"enabled": True, "service_name": "test"},
            "otlp": {"enabled": True, "endpoint": "http://localhost:4317"},
        }
        mock_tp.return_value = MagicMock()

        with patch("opentelemetry.sdk.trace.export.SimpleSpanProcessor"), \
             patch("animetta.tracing.exporter.StatsSpanExporter"), \
             patch("opentelemetry.sdk.resources.Resource"), \
             patch("animetta.tracing.bootstrap._init_otlp_exporter") as mock_otlp, \
             patch("animetta.tracing.metrics.init_metrics"):
            init_tracing()
            mock_otlp.assert_called_once()
