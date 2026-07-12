"""Recorder-backed dynamic proxy for async service operations."""

from __future__ import annotations

import asyncio
import functools
import inspect
import time
import uuid
from typing import Any

from .context import (
    ObservationContext,
    attach_observation_context,
    detach_observation_context,
    get_observation_context,
)
from .domain import (
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
)
from .errors import classify_error
from .ports import NoOpObservationRecorder, ObservationRecorder


def instrument_service(
    target: Any,
    recorder: ObservationRecorder | None,
    service_name: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> InstrumentedServiceProxy:
    if isinstance(target, InstrumentedServiceProxy):
        return target
    return InstrumentedServiceProxy(
        target,
        recorder or NoOpObservationRecorder(),
        service_name,
        provider=provider,
        model=model,
    )


class InstrumentedServiceProxy:
    """Observe async methods without recording arguments, results, or payloads."""

    def __init__(
        self,
        target: Any,
        recorder: ObservationRecorder,
        service_name: str,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_recorder", recorder)
        object.__setattr__(self, "_service", service_name)
        object.__setattr__(self, "_provider", provider)
        object.__setattr__(self, "_model", model)

    def __getattr__(self, name: str) -> Any:
        target = object.__getattribute__(self, "_target")
        raw = getattr(target, name)
        if name.startswith("_"):
            return raw
        if inspect.isasyncgenfunction(raw):

            @functools.wraps(raw)
            async def observed_generator(*args: Any, **kwargs: Any):
                parent = get_observation_context()
                if parent is None:
                    async for item in raw(*args, **kwargs):
                        yield item
                    return

                started, child = await self._start(name, parent)
                iterator = raw(*args, **kwargs).__aiter__()
                completed = False
                try:
                    while True:
                        token = attach_observation_context(child)
                        try:
                            item = await anext(iterator)
                        except StopAsyncIteration:
                            completed = True
                            break
                        finally:
                            detach_observation_context(token)
                        yield item
                except asyncio.CancelledError:
                    await self._finish(started, OperationStatus.CANCELLED)
                    raise
                except Exception as exc:
                    await self._finish_error(started, exc)
                    raise
                finally:
                    if completed:
                        await self._finish(started, OperationStatus.SUCCESS)
                    elif not started["finished"]:
                        await self._finish(started, OperationStatus.CANCELLED)

            return observed_generator

        if asyncio.iscoroutinefunction(raw):

            @functools.wraps(raw)
            async def observed_call(*args: Any, **kwargs: Any) -> Any:
                parent = get_observation_context()
                if parent is None:
                    return await raw(*args, **kwargs)
                started, child = await self._start(name, parent)
                token = attach_observation_context(child)
                try:
                    result = await raw(*args, **kwargs)
                except asyncio.CancelledError:
                    await self._finish(started, OperationStatus.CANCELLED)
                    raise
                except Exception as exc:
                    await self._finish_error(started, exc)
                    raise
                finally:
                    detach_observation_context(token)
                await self._finish(started, OperationStatus.SUCCESS)
                return result

            return observed_call

        return raw

    async def _start(
        self,
        method: str,
        parent: ObservationContext,
    ) -> tuple[dict[str, Any], ObservationContext]:
        recorder = object.__getattribute__(self, "_recorder")
        service = object.__getattribute__(self, "_service")
        provider = object.__getattribute__(self, "_provider")
        model = object.__getattribute__(self, "_model")
        operation_id = uuid.uuid4().hex
        await recorder.start_operation(
            OperationStarted(
                operation_id=operation_id,
                trace_id=parent.trace_id,
                parent_operation_id=parent.operation_id or parent.parent_operation_id,
                layer=ObservationLayer.SERVICE,
                name=f"{service}.{method}",
                critical_path=parent.critical_path,
                started_at=time.time(),
                provider=provider,
                model=model,
                attributes={
                    "method": method,
                    "provider": provider,
                    "model": model,
                },
            )
        )
        child = ObservationContext(
            trace_id=parent.trace_id,
            operation_id=operation_id,
            parent_operation_id=parent.operation_id or parent.parent_operation_id,
            message_id=parent.message_id,
            conversation_id=parent.conversation_id,
            session_id=parent.session_id,
            privacy_mode=parent.privacy_mode,
            critical_path=parent.critical_path,
        )
        return {"operation_id": operation_id, "finished": False}, child

    async def _finish(
        self,
        started: dict[str, Any],
        status: OperationStatus,
        *,
        error_type: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        if started["finished"]:
            return
        started["finished"] = True
        recorder = object.__getattribute__(self, "_recorder")
        await recorder.finish_operation(
            OperationFinished(
                started["operation_id"],
                status,
                time.time(),
                error_type=error_type,
                error_summary=error_summary,
            )
        )

    async def _finish_error(
        self,
        started: dict[str, Any],
        error: Exception,
    ) -> None:
        await self._finish(
            started,
            OperationStatus.ERROR,
            error_type=classify_error(error).value,
            error_summary=type(error).__name__,
        )

    def __bool__(self) -> bool:
        return bool(object.__getattribute__(self, "_target"))

    def __aiter__(self):
        return object.__getattribute__(self, "_target").__aiter__()

    def __repr__(self) -> str:
        target = object.__getattribute__(self, "_target")
        return f"<InstrumentedServiceProxy of {target!r}>"
