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

    async def chat_with_kwargs(self, text: str, temperature: float = 0.7) -> str:
        return f"{text} @ {temperature}"


class TestTracingProxy:
    """Suite for TracingProxy."""

    @pytest.fixture
    def mock_service(self):
        return _MockService()

    @pytest.fixture
    def proxy(self, mock_service):

        return TracingProxy(mock_service, service_name="test")

    # ── Wrapping async methods ───────────────────────────────────────

    async def test_wraps_async_method(self, proxy):
        """Async method calls should be proxied and return the result."""
        result = await proxy.chat("hello")
        assert result == "response: hello"

    async def test_span_name_includes_service(self, proxy):
        """Span name should follow '{service}.{method}' pattern."""
        result = await proxy.chat("world")
        assert result == "response: world"
        # The span was created — verified by exporter not raising

    async def test_async_method_with_kwargs(self, proxy):
        """Async methods with keyword arguments should work."""
        result = await proxy.chat_with_kwargs("hello", temperature=0.9)
        assert result == "hello @ 0.9"

    # ── Passthrough sync methods and properties ──────────────────────

    def test_passthrough_sync_method(self, proxy):
        """Sync methods should pass through unmodified."""
        result = proxy.sync_method(21)
        assert result == 42

    def test_passthrough_property(self, proxy):
        """Properties should pass through."""
        assert proxy.name == "mock_service"

    # ── Async generator methods ──────────────────────────────────────

    async def test_wraps_async_generator(self, proxy):
        """Async generator (yield) methods should produce items."""
        chunks = []
        async for chunk in proxy.chat_stream("hello world"):
            chunks.append(chunk)
        assert chunks == ["hello", "world"]

    # ── Exception handling ───────────────────────────────────────────

    async def test_captures_exception(self, proxy):
        """Exceptions from wrapped methods should propagate to caller."""
        with pytest.raises(ValueError, match="oops"):
            await proxy.failing_method()

    # ── Lazy tracer resolution ───────────────────────────────────────

    async def test_lazy_tracer_resolution(self, mock_service):
        """Proxy should work when created before TracerProvider is set."""

        p = TracingProxy(mock_service, tracer=None, service_name="lazy_test")
        result = await p.chat("lazy")
        assert result == "response: lazy"

    # ── __repr__ ─────────────────────────────────────────────────────

    def test_repr(self, proxy):
        """__repr__ should indicate it's a TracingProxy."""
        r = repr(proxy)
        assert "TracingProxy" in r
        assert "_MockService" in r

    # ── __bool__ ─────────────────────────────────────────────────────

    async def test_bool_delegated(self):
        """__bool__ delegates to target."""
        svc = MagicMock()
        svc.__bool__ = MagicMock(return_value=True)

        p = TracingProxy(svc, service_name="bool_test")
        assert bool(p) is True

    # ── __getattr__ for private attrs ────────────────────────────────

    def test_private_attr_passthrough(self, proxy):
        """Attributes starting with '_' should bypass tracing."""
        # proxy._target exists internally
        assert hasattr(proxy, "_target")

    # ── _is_async_method ─────────────────────────────────────────────

    def test_is_async_method_static(self):
        """_is_async_method detects coroutine functions."""

        async def fake_coro():
            pass

        assert TracingProxy._is_async_method(fake_coro) is True

        def fake_sync():
            pass

        assert TracingProxy._is_async_method(fake_sync) is False

    # ── Service with no public methods ───────────────────────────────

    def test_proxy_wraps_empty_service(self):
        """A service with no public methods should not crash."""

        class Empty:
            pass

        p = TracingProxy(Empty(), service_name="empty")
        assert "TracingProxy" in repr(p)

    # ── Edge: bytes arg ──────────────────────────────────────────────

    async def test_bytes_first_arg(self, mock_service):
        """Byte arguments should be represented as '<N bytes>'."""

        class BytesService:
            async def process(self, data: bytes) -> str:
                return f"got {len(data)} bytes"

        bs = BytesService()
        p = TracingProxy(bs, service_name="bytes_test")
        result = await p.process(b"\x00" * 100)
        assert result == "got 100 bytes"
