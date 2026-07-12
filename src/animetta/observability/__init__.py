"""Local-first observability contracts and infrastructure."""

from .context import ObservationCarrier, ObservationContext, get_observation_context
from .domain import (
    EventDirection,
    ObservationEvent,
    ObservationHealth,
    ObservationLayer,
    OperationFinished,
    OperationStarted,
    OperationStatus,
    PrivacyMode,
    TraceFinished,
    TraceIdentity,
    TraceOutcome,
    TraceStarted,
)
from .errors import ErrorType, classify_error, normalize_error_type
from .ports import ObservationQuery, ObservationRecorder
from .privacy import ObservationContentPolicy

__all__ = [
    "EventDirection",
    "ErrorType",
    "ObservationCarrier",
    "ObservationContentPolicy",
    "ObservationContext",
    "ObservationEvent",
    "ObservationHealth",
    "ObservationLayer",
    "ObservationQuery",
    "ObservationRecorder",
    "OperationFinished",
    "OperationStarted",
    "OperationStatus",
    "PrivacyMode",
    "TraceFinished",
    "TraceIdentity",
    "TraceOutcome",
    "TraceStarted",
    "classify_error",
    "get_observation_context",
    "normalize_error_type",
]
