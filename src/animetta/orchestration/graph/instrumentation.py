"""LangGraph node instrumentation backed by the observation recorder port."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Any, TypeVar

from animetta.observability.context import (
    ObservationContext,
    get_observation_context,
    observation_context,
)
from animetta.observability.domain import (
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
)
from animetta.observability.errors import classify_error
from animetta.observability.ports import ObservationRecorder

NodeResult = TypeVar("NodeResult")
Node = Callable[..., Awaitable[NodeResult]]


def instrument_node(name: str, node: Node, recorder: ObservationRecorder) -> Node:
    """Record exactly one workflow operation for each actual node invocation."""

    @wraps(node)
    async def observed(*args: Any, **kwargs: Any) -> NodeResult:
        parent = get_observation_context()
        if parent is None:
            return await node(*args, **kwargs)

        operation_id = uuid.uuid4().hex
        started_at = time.time()
        await recorder.start_operation(
            OperationStarted(
                operation_id=operation_id,
                trace_id=parent.trace_id,
                parent_operation_id=parent.operation_id or parent.parent_operation_id,
                layer=ObservationLayer.WORKFLOW,
                name=name,
                critical_path=True,
                started_at=started_at,
                attributes={"node_name": name},
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
            critical_path=True,
        )
        try:
            with observation_context(child):
                result = await node(*args, **kwargs)
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

        await recorder.finish_operation(
            OperationFinished(
                operation_id,
                _returned_status(result),
                time.time(),
            )
        )
        return result

    observed.observation_node_name = name  # type: ignore[attr-defined]
    return observed


def _returned_status(result: object) -> OperationStatus:
    if not isinstance(result, Mapping):
        return OperationStatus.SUCCESS
    if result.get("error"):
        return OperationStatus.ERROR
    metadata = result.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("degradation_reason"):
        return OperationStatus.DEGRADED
    if result.get("status") == "skipped":
        return OperationStatus.SKIPPED
    return OperationStatus.SUCCESS
