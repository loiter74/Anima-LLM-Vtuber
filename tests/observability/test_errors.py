import asyncio

import pytest

from animetta.observability.errors import ErrorType, classify_error, normalize_error_type


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("late"), ErrorType.TIMEOUT),
        (ConnectionError("offline"), ErrorType.NETWORK_ERROR),
        (RuntimeError("HTTP 429 rate limited"), ErrorType.RATE_LIMIT),
        (ValueError("empty provider response"), ErrorType.INVALID_RESPONSE),
        (asyncio.CancelledError(), ErrorType.CANCELLED),
        (RuntimeError("unexpected"), ErrorType.UNKNOWN),
    ],
)
def test_classify_error_uses_bounded_categories(error: BaseException, expected: ErrorType) -> None:
    assert classify_error(error) is expected


def test_unknown_error_type_is_normalized() -> None:
    assert normalize_error_type("cosmic_ray") is ErrorType.UNKNOWN
    assert normalize_error_type("delivery_error") is ErrorType.DELIVERY_ERROR
