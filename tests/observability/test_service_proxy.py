import asyncio

import pytest

from animetta.observability.context import ObservationContext, observation_context
from animetta.observability.domain import (
    ObservationLayer,
    OperationStatus,
    PrivacyMode,
)
from animetta.observability.service_proxy import InstrumentedServiceProxy


class Recorder:
    def __init__(self) -> None:
        self.started = []
        self.finished = []

    async def start_operation(self, record) -> None:
        self.started.append(record)

    async def finish_operation(self, record) -> None:
        self.finished.append(record)


class Service:
    model = "model-1"

    async def call(self, secret: str) -> str:
        return f"ok:{secret}"

    async def nested(self) -> str:
        return await self.child()

    async def child(self) -> str:
        return "child"

    async def stream(self, secret: str):
        yield secret
        yield "done"

    async def fail(self) -> None:
        raise ConnectionError("api_key=secret")

    async def cancel(self) -> None:
        raise asyncio.CancelledError


def _root() -> ObservationContext:
    return ObservationContext(
        "task-1",
        "reasoner-op",
        None,
        "message-1",
        "conversation-1",
        "socket-1",
        PrivacyMode.REDACTED,
    )


async def test_async_method_records_service_parent_provider_model_without_payload() -> None:
    recorder = Recorder()
    proxy = InstrumentedServiceProxy(
        Service(), recorder, "llm", provider="deepseek", model="model-1"
    )

    with observation_context(_root()):
        result = await proxy.call("top-secret-prompt")

    assert result == "ok:top-secret-prompt"
    operation = recorder.started[0]
    assert operation.layer is ObservationLayer.SERVICE
    assert operation.name == "llm.call"
    assert operation.parent_operation_id == "reasoner-op"
    assert operation.provider == "deepseek"
    assert operation.model == "model-1"
    assert "top-secret-prompt" not in repr(operation)
    assert recorder.finished[0].status is OperationStatus.SUCCESS


async def test_async_generator_restores_parent_context_between_chunks() -> None:
    from animetta.observability.context import get_observation_context

    recorder = Recorder()
    proxy = InstrumentedServiceProxy(Service(), recorder, "llm")
    contexts = []
    chunks = []
    with observation_context(_root()):
        async for chunk in proxy.stream("secret-stream"):
            chunks.append(chunk)
            contexts.append(get_observation_context().operation_id)

    assert chunks == ["secret-stream", "done"]
    assert contexts == ["reasoner-op", "reasoner-op"]
    assert recorder.finished[0].status is OperationStatus.SUCCESS


async def test_nested_proxies_preserve_runtime_parentage() -> None:
    recorder = Recorder()
    child = InstrumentedServiceProxy(Service(), recorder, "tts")

    class Parent:
        async def call(self):
            return await child.call("nested")

    parent = InstrumentedServiceProxy(Parent(), recorder, "llm")
    with observation_context(_root()):
        await parent.call()

    outer, inner = recorder.started
    assert outer.name == "llm.call"
    assert inner.name == "tts.call"
    assert inner.parent_operation_id == outer.operation_id


@pytest.mark.parametrize(
    ("method", "status"),
    [("fail", OperationStatus.ERROR), ("cancel", OperationStatus.CANCELLED)],
)
async def test_errors_and_cancellation_are_typed_and_propagated(method, status) -> None:
    recorder = Recorder()
    proxy = InstrumentedServiceProxy(Service(), recorder, "llm")
    expected = ConnectionError if method == "fail" else asyncio.CancelledError

    with observation_context(_root()), pytest.raises(expected):
        await getattr(proxy, method)()

    assert recorder.finished[0].status is status
    assert "secret" not in repr(recorder.finished[0])
