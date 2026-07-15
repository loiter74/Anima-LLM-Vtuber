"""
TracingProxy — dynamic proxy that wraps service instances with OTel spans.

Usage:
    from opentelemetry import trace
    from anima.tracing import TracingProxy

    tracer = trace.get_tracer("anima")
    real_service = GLMLLM(config)
    traced = TracingProxy(real_service, tracer, "llm")
    await traced.chat_stream("你好")  # → auto-creates span "llm.chat_stream"
"""

import asyncio
import functools
import inspect
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

_INPUT_TRUNCATE_LEN = 200


class TracingProxy:
    """Wraps an arbitrary service instance and creates OTel spans for each async method call.

    Spans are created with the name ``{service_name}.{method_name}`` and
    automatically inherit the current trace context (trace_id / parent_span_id)
    from the OTel ContextVar, which is set in LangGraph node functions.

    Usage::

        tracer = trace.get_tracer("anima")
        proxy = TracingProxy(llm_engine, tracer, "llm")
        result = await proxy.chat_stream("hello")  # auto-traced
    """

    _DEFAULT_TRACER_NAME = "anima"

    def __init__(self, target: Any, tracer: trace.Tracer | None = None, service_name: str = ""):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_tracer", tracer)  # None = resolve lazily
        object.__setattr__(self, "_service", service_name)
        object.__setattr__(
            self, "_public_methods", {name for name in dir(target) if not name.startswith("_")}
        )

    def _get_tracer(self) -> trace.Tracer:
        tracer = object.__getattribute__(self, "_tracer")
        if tracer is not None:
            return tracer
        # Lazy resolution: pick up whatever TracerProvider is currently configured
        tracer = trace.get_tracer(self._DEFAULT_TRACER_NAME)
        object.__setattr__(self, "_tracer", tracer)
        return tracer

    # ── attribute passthrough for non-callable / sync attrs ──

    def __getattr__(self, name: str) -> Any:
        """Intercept attribute access on the wrapped target."""
        target = object.__getattribute__(self, "_target")
        raw = getattr(target, name)
        if name.startswith("_"):
            return raw

        service = object.__getattribute__(self, "_service")

        # Handle async generators (async def with yield) — e.g. chat_stream
        if inspect.isasyncgenfunction(raw):

            @functools.wraps(raw)
            async def _traced_gen(*args, **kwargs):
                tracer = self._get_tracer()
                span_name = f"{service}.{name}"
                with tracer.start_as_current_span(span_name) as span:
                    try:
                        async for item in raw(*args, **kwargs):
                            yield item
                        span.set_status(Status(StatusCode.OK))
                    except Exception as e:
                        span.set_status(Status(StatusCode.ERROR, str(e)[:500]))
                        span.record_exception(e)
                        raise

            return _traced_gen

        # Handle coroutine functions (async def) — e.g. chat, synthesize, transcribe
        if asyncio.iscoroutinefunction(raw):

            @functools.wraps(raw)
            async def _traced_call(*args, **kwargs):
                tracer = self._get_tracer()
                return await self._call_with_span(tracer, service, name, raw, args, kwargs)

            return _traced_call

        # Non-callable or sync — pass through
        return raw

    # ── span creation ──

    @staticmethod
    async def _call_with_span(
        tracer: trace.Tracer,
        service: str,
        method: str,
        coro_fn,
        args: tuple,
        kwargs: dict,
    ) -> Any:
        span_name = f"{service}.{method}"
        attrs = {}

        # Record truncated first arg as attribute (PII-safe)
        if args:
            first = str(args[0]) if not isinstance(args[0], bytes) else f"<{len(args[0])} bytes>"
            attrs["arg.0"] = first[:_INPUT_TRUNCATE_LEN]
        if kwargs:
            safe_keys = [
                k
                for k in list(kwargs.keys())[:3]
                if k.lower() not in ("api_key", "secret", "password", "token")
            ]
            if safe_keys:
                attrs["kwarg_keys"] = ",".join(safe_keys)

        with tracer.start_as_current_span(span_name, attributes=attrs or None) as span:
            try:
                result = await coro_fn(*args, **kwargs)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)[:500]))
                span.record_exception(e)
                raise

    # ── helpers ──

    @staticmethod
    def _is_async_method(obj: Any) -> bool:
        return asyncio.iscoroutinefunction(obj) or inspect.isasyncgenfunction(obj)

    # ── delegate special methods to target ──

    def __bool__(self) -> bool:
        """Truthiness: proxy is truthy if target is truthy (safe for 'if proxy:' checks)."""
        return bool(object.__getattribute__(self, "_target"))

    def __aiter__(self):
        return object.__getattribute__(self, "_target").__aiter__()

    def __repr__(self) -> str:
        target = object.__getattribute__(self, "_target")
        return f"<TracingProxy of {target!r}>"
