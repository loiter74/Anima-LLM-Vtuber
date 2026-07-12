"""Reusable operation scope for adapters outside LangGraph node wrapping."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from .context import (
    ObservationContext,
    attach_observation_context,
    detach_observation_context,
    get_observation_context,
)
from .domain import (
    AttributeValue,
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
)
from .errors import classify_error
from .ports import ObservationRecorder


@asynccontextmanager
async def observe_operation(
    recorder: ObservationRecorder,
    name: str,
    *,
    layer: ObservationLayer,
    critical_path: bool,
    attributes: Mapping[str, AttributeValue] | None = None,
) -> AsyncIterator[ObservationContext | None]:
    parent = get_observation_context()
    if parent is None:
        yield None
        return
    operation_id = uuid.uuid4().hex
    await recorder.start_operation(
        OperationStarted(
            operation_id=operation_id,
            trace_id=parent.trace_id,
            parent_operation_id=parent.operation_id or parent.parent_operation_id,
            layer=layer,
            name=name,
            critical_path=critical_path,
            started_at=time.time(),
            attributes=attributes or {},
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
        critical_path=critical_path,
    )
    token = attach_observation_context(child)
    try:
        yield child
    except asyncio.CancelledError:
        await recorder.finish_operation(
            OperationFinished(
                operation_id,
                OperationStatus.CANCELLED,
                time.time(),
                error_type="cancelled",
            )
        )
        raise
    except Exception as exc:
        await recorder.finish_operation(
            OperationFinished(
                operation_id,
                OperationStatus.ERROR,
                time.time(),
                error_type=classify_error(exc).value,
                error_summary=type(exc).__name__,
            )
        )
        raise
    else:
        await recorder.finish_operation(
            OperationFinished(operation_id, OperationStatus.SUCCESS, time.time())
        )
    finally:
        detach_observation_context(token)
