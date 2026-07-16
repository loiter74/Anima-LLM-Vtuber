"""Structured observation error classification."""

import asyncio
from enum import StrEnum


class ErrorType(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    NETWORK_ERROR = "network_error"
    INVALID_RESPONSE = "invalid_response"
    SERVICE_UNAVAILABLE = "service_unavailable"
    DELIVERY_ERROR = "delivery_error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


def normalize_error_type(value: str | ErrorType | None) -> ErrorType:
    if isinstance(value, ErrorType):
        return value
    try:
        return ErrorType(str(value))
    except ValueError:
        return ErrorType.UNKNOWN


def classify_error(error: BaseException) -> ErrorType:
    if isinstance(error, asyncio.CancelledError):
        return ErrorType.CANCELLED
    if isinstance(error, TimeoutError):
        return ErrorType.TIMEOUT
    if isinstance(error, ConnectionError):
        return ErrorType.NETWORK_ERROR

    message = str(error).casefold()
    if "429" in message or "rate limit" in message:
        return ErrorType.RATE_LIMIT
    if "service unavailable" in message or "not initialized" in message:
        return ErrorType.SERVICE_UNAVAILABLE
    if (
        isinstance(error, ValueError)
        or "invalid response" in message
        or "empty response" in message
    ):
        return ErrorType.INVALID_RESPONSE
    return ErrorType.UNKNOWN
