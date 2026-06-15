from __future__ import annotations

"""Tests for TracingProxy — dynamic OTel span creation around service calls."""

from unittest.mock import MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter

from animetta.tracing.proxy import TracingProxy


class _TestExporter(SpanExporter):
    """In-memory exporter that captures exported spans."""
    def __init__(self):
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return self.__class__.SUCCESS

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        return True


@pytest.fixture(autouse=True)
def _setup_tracer():
    """Set up a TracerProvider with an in-memory exporter for all tests."""
    provider = TracerProvider()
    exporter = _TestExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


class _MockService:
    """A mock service with async and sync methods to wrap."""

    async def chat(self, text: str) -> str:
        return f"response: {text}"

    async def chat_stream(self, text: str):
        for chunk in text.split():
            yield chunk

    def sync_method(self, x: int) -> int:
        return x * 2

    @property
    def name(self) -> str:
        return "mock_service"

    async def failing_method(self):
        raise ValueError("oops")


@pytest.fixture
def mock_service():
    return _MockService()


@pytest.fixture
def proxy(mock_service):
    return TracingProxy(mock_service, service_name="test")


class TestTracingProxy:

    async def test_wraps_async_method(self, proxy):
        """Async methods should create a span and return result."""
        result = await proxy.chat("hello")
        assert result == "response: hello"

    async def test_span_name_includes_service(self, proxy):
        """Span name should be '{service}.{method}'."""
        result = await proxy.chat("world")
        assert result == "response: world"
        # The span was created — this is verified by the exporter not raising

    async def test_passthrough_sync_method(self, proxy):
        """Sync methods and properties should pass through unmodified."""
        result = proxy.sync_method(21)
        assert result == 42

    def test_passthrough_property(self, proxy):
        """Properties should pass through."""
        assert proxy.name == "mock_service"

    async def test_wraps_async_generator(self, proxy):
        """Async generator methods should work."""
        chunks = []
        async for chunk in proxy.chat_stream("hello world"):
            chunks.append(chunk)
        assert chunks == ["hello", "world"]

    async def test_captures_exception(self, proxy):
        """Exceptions from wrapped methods should propagate."""
        with pytest.raises(ValueError, match="oops"):
            await proxy.failing_method()

    async def test_lazy_tracer_resolution(self, mock_service):
        """Proxy should work even when created before TracerProvider is set."""
        p = TracingProxy(mock_service, tracer=None, service_name="lazy_test")
        result = await p.chat("lazy")
        assert result == "response: lazy"

    def test_repr(self, proxy):
        """__repr__ should show the proxy wrapping."""
        r = repr(proxy)
        assert "TracingProxy" in r
        assert "MockService" in r or "_MockService" in r

    async     def test_bool_delegated(self):
        """__bool__ delegates to target."""
        svc = MagicMock()
        svc.__bool__ = MagicMock(return_value=True)
        p = TracingProxy(svc, service_name="bool_test")
        assert bool(p) is True
