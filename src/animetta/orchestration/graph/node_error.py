"""Active-context structured error facade for LangGraph nodes."""

import time
import uuid

from loguru import logger

from animetta.observability.context import (
    get_observation_context,
    get_observation_recorder,
)
from animetta.observability.domain import EventDirection, ObservationEvent

LOGGER = logger.bind(name="NodeError")

VALID_ERROR_TYPES: frozenset[str] = frozenset({
    "timeout",
    "rate_limit",
    "network_error",
    "invalid_response",
})


async def log_node_error(
    session_id: str,
    node_name: str,
    error_type: str,
    provider: str = "",
    duration_ms: float = 0.0,
) -> None:
    """Log and append one sanitized event under the active node context."""
    if error_type not in VALID_ERROR_TYPES:
        LOGGER.debug(
            f"[{session_id}] Unknown error_type '{error_type}', "
            f"mapping to 'unknown'"
        )
        error_type = "unknown"

    LOGGER.warning(
        f"[{session_id}] [{node_name}] Provider error: "
        f"type={error_type} provider={provider} duration={duration_ms:.0f}ms"
    )

    context = get_observation_context()
    recorder = get_observation_recorder()
    record_event = getattr(recorder, "record_event", None)
    if context is None or not callable(record_event):
        return
    await record_event(
        ObservationEvent(
            event_id=uuid.uuid4().hex,
            trace_id=context.trace_id,
            operation_id=context.operation_id,
            direction=EventDirection.INTERNAL,
            name=f"{node_name}.error",
            phase="error",
            occurred_at=time.time(),
            payload_size=0,
            identity_valid=True,
            attributes={
                "error_type": error_type,
                "provider": provider,
                "duration_ms": round(duration_ms, 2),
                "node_name": node_name,
            },
        )
    )
