"""Tests for the pipeline smoke test check."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.inspection.checks.pipeline import EXPECTED_EVENTS, check_conversation_pipeline
from animetta.inspection.models import CheckResult

# ── Helpers ──────────────────────────────────────────────────────────


def _create_mock_client(
    *,
    connect_side_effect: Exception | None = None,
    wildcard_handler_container: list | None = None,
) -> MagicMock:
    """Create a mock socketio.AsyncClient instance.

    Args:
        connect_side_effect: If set, sio.connect() raises this.
        wildcard_handler_container: If provided, the wildcard handler
            registered via @sio.on("*") is stored in container[0].
    """
    client = MagicMock()
    client.connect = AsyncMock(side_effect=connect_side_effect)
    client.emit = AsyncMock()
    client.disconnect = AsyncMock()

    if wildcard_handler_container is not None:
        def _on(event: str):
            def decorator(func):
                wildcard_handler_container[0] = func
                return func
            return decorator
        client.on = _on
    else:
        # Default: on() returns a decorator that returns the function unchanged
        client.on = MagicMock(return_value=lambda f: f)

    return client


# ── Tests ────────────────────────────────────────────────────────────


class TestSuccessfulPipeline:
    """Happy path: all expected events received."""

    @pytest.mark.asyncio
    async def test_all_expected_events_received(self):
        """Pipeline smoke test passes when all EXPECTED_EVENTS arrive."""
        wildcard_handler: list = [None]

        mock_client = _create_mock_client(
            wildcard_handler_container=wildcard_handler,
        )

        # Patch asyncio.sleep to simulate events arriving during the wait
        original_sleep = asyncio.sleep

        async def _mock_sleep(duration: float) -> None:
            handler = wildcard_handler[0]
            if handler is not None:
                for event_name in sorted(EXPECTED_EVENTS):
                    await handler(event_name, {})
            # Don't actually wait — just yield control
            await original_sleep(0)

        with (
            patch(
                "animetta.inspection.checks.pipeline.socketio.AsyncClient",
                return_value=mock_client,
            ),
            patch("animetta.inspection.checks.pipeline.asyncio.sleep", _mock_sleep),
        ):
            result = await check_conversation_pipeline()

        assert isinstance(result, CheckResult)
        assert result.ok is True
        assert result.name == "pipeline/conversation"
        assert result.error is None
        result_received = set(result.detail.get("received", []))
        assert result_received >= set(EXPECTED_EVENTS), (
            f"Expected {set(EXPECTED_EVENTS)} ⊆ {result_received}"
        )
        assert result.detail.get("missing") == []

        # Verify the test message was emitted
        mock_client.emit.assert_called_once()
        call_args = mock_client.emit.call_args
        assert call_args[0][0] == "chat:text"
        assert call_args[0][1]["text"] == "[inspection] ping"
        assert call_args[0][1]["mode"] == "text"

    @pytest.mark.asyncio
    async def test_extra_events_do_not_break_success(self):
        """Receiving additional events beyond EXPECTED_EVENTS still passes."""
        wildcard_handler: list = [None]

        mock_client = _create_mock_client(
            wildcard_handler_container=wildcard_handler,
        )

        original_sleep = asyncio.sleep

        async def _mock_sleep(duration: float) -> None:
            handler = wildcard_handler[0]
            if handler is not None:
                # Send expected events plus extras
                for event_name in ["control", *sorted(EXPECTED_EVENTS), "live2d.action"]:
                    await handler(event_name, {})
            await original_sleep(0)

        with (
            patch(
                "animetta.inspection.checks.pipeline.socketio.AsyncClient",
                return_value=mock_client,
            ),
            patch("animetta.inspection.checks.pipeline.asyncio.sleep", _mock_sleep),
        ):
            result = await check_conversation_pipeline()

        assert result.ok is True
        assert result.detail.get("missing") == []


class TestConnectionTimeout:
    """Connection timeout error handling."""

    @pytest.mark.asyncio
    async def test_connect_timeout_returns_failed(self):
        """Returns CheckResult.failed when socketio.connect times out."""
        mock_client = _create_mock_client(
            connect_side_effect=TimeoutError(),
        )

        with patch(
            "animetta.inspection.checks.pipeline.socketio.AsyncClient",
            return_value=mock_client,
        ):
            result = await check_conversation_pipeline()

        assert isinstance(result, CheckResult)
        assert result.ok is False
        assert result.name == "pipeline/conversation"
        assert "timed out" in result.error.lower()
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_wait_for_timeout_returns_failed(self):
        """Returns CheckResult.failed when asyncio.wait_for hits timeout."""
        mock_client = _create_mock_client()
        # Simulate wait_for timing out (connect never completes)
        timeout_error = TimeoutError()

        with (
            patch(
                "animetta.inspection.checks.pipeline.socketio.AsyncClient",
                return_value=mock_client,
            ),
            patch(
                "animetta.inspection.checks.pipeline.asyncio.wait_for",
                side_effect=timeout_error,
            ),
        ):
            result = await check_conversation_pipeline()

        assert result.ok is False
        assert "timed out" in result.error.lower()


class TestMissingEvents:
    """Partial pipeline: some expected events not received."""

    @pytest.mark.asyncio
    async def test_missing_events_returns_failed(self):
        """Returns CheckResult.failed with missing event detail."""
        wildcard_handler: list = [None]

        mock_client = _create_mock_client(
            wildcard_handler_container=wildcard_handler,
        )

        original_sleep = asyncio.sleep

        async def _mock_sleep(duration: float) -> None:
            handler = wildcard_handler[0]
            if handler is not None:
                # Only send expression — audio_with_expression and sentence are missing
                await handler("expression", {})
            await original_sleep(0)

        with (
            patch(
                "animetta.inspection.checks.pipeline.socketio.AsyncClient",
                return_value=mock_client,
            ),
            patch("animetta.inspection.checks.pipeline.asyncio.sleep", _mock_sleep),
        ):
            result = await check_conversation_pipeline()

        assert isinstance(result, CheckResult)
        assert result.ok is False
        assert result.name == "pipeline/conversation"
        assert "missing" in result.error.lower()

        missing = set(result.detail.get("missing", []))
        received = set(result.detail.get("received", []))

        # Verify only expression was received, others are missing
        assert "expression" in received
        assert "audio_with_expression" in missing
        assert "sentence" in missing

    @pytest.mark.asyncio
    async def test_no_events_received(self):
        """Returns failed when zero events are received."""
        wildcard_handler: list = [None]

        mock_client = _create_mock_client(
            wildcard_handler_container=wildcard_handler,
        )

        original_sleep = asyncio.sleep

        async def _mock_sleep(duration: float) -> None:
            # No events fired at all
            await original_sleep(0)

        with (
            patch(
                "animetta.inspection.checks.pipeline.socketio.AsyncClient",
                return_value=mock_client,
            ),
            patch("animetta.inspection.checks.pipeline.asyncio.sleep", _mock_sleep),
        ):
            result = await check_conversation_pipeline()

        assert result.ok is False
        assert len(result.detail.get("received", [])) == 0
        assert len(result.detail.get("missing", [])) == len(EXPECTED_EVENTS)


class TestExceptionDuringConnection:
    """Exception handling during pipeline execution."""

    @pytest.mark.asyncio
    async def test_runtime_error_during_connect(self):
        """RuntimeError during connect is caught and reported as failure."""
        mock_client = _create_mock_client(
            connect_side_effect=RuntimeError("Connection refused"),
        )

        with patch(
            "animetta.inspection.checks.pipeline.socketio.AsyncClient",
            return_value=mock_client,
        ):
            result = await check_conversation_pipeline()

        assert isinstance(result, CheckResult)
        assert result.ok is False
        assert "RuntimeError" in result.error or "Connection refused" in result.error
        assert result.detail.get("received") == []

    @pytest.mark.asyncio
    async def test_exception_during_disconnect_is_caught(self):
        """Exception during disconnect is caught by outer handler, returns failed."""
        wildcard_handler: list = [None]

        mock_client = _create_mock_client(
            wildcard_handler_container=wildcard_handler,
        )
        mock_client.disconnect = AsyncMock(side_effect=RuntimeError("Disconnect failed"))

        original_sleep = asyncio.sleep

        async def _mock_sleep(duration: float) -> None:
            handler = wildcard_handler[0]
            if handler is not None:
                for event_name in sorted(EXPECTED_EVENTS):
                    await handler(event_name, {})
            await original_sleep(0)

        with (
            patch(
                "animetta.inspection.checks.pipeline.socketio.AsyncClient",
                return_value=mock_client,
            ),
            patch("animetta.inspection.checks.pipeline.asyncio.sleep", _mock_sleep),
        ):
            result = await check_conversation_pipeline()

        # Outer try/except catches the disconnect exception
        assert isinstance(result, CheckResult)
        assert result.ok is False
        assert "Disconnect failed" in result.error or "Exception" in result.error


class TestEventNames:
    """Verify that EXPECTED_EVENTS match actual codebase emits."""

    def test_expected_events_are_from_codebase(self):
        """EXPECTED_EVENTS must contain only verified event names.

        These names are verified against actual Socket.IO emit() calls
        in the orchestration graph nodes (output_node.py, asr_node.py).
        """
        # Must be a frozenset (immutable, hashable)
        assert isinstance(EXPECTED_EVENTS, frozenset)

        # All three core pipeline events must be present
        assert "expression" in EXPECTED_EVENTS
        assert "audio_with_expression" in EXPECTED_EVENTS
        assert "sentence" in EXPECTED_EVENTS

        # Must match the expected count (currently 3)
        assert len(EXPECTED_EVENTS) == 3, (
            f"EXPECTED_EVENTS has {len(EXPECTED_EVENTS)} entries; "
            f"verify against codebase emit() calls before changing"
        )


class TestCheckResultShape:
    """Verify the structure of returned CheckResult objects."""

    @pytest.mark.asyncio
    async def test_failed_result_contains_diagnostic_fields(self):
        """Failed results include 'received' and 'missing' in detail."""
        wildcard_handler: list = [None]

        mock_client = _create_mock_client(
            wildcard_handler_container=wildcard_handler,
        )

        original_sleep = asyncio.sleep

        async def _mock_sleep(duration: float) -> None:
            handler = wildcard_handler[0]
            if handler is not None:
                await handler("expression", {})
            await original_sleep(0)

        with (
            patch(
                "animetta.inspection.checks.pipeline.socketio.AsyncClient",
                return_value=mock_client,
            ),
            patch("animetta.inspection.checks.pipeline.asyncio.sleep", _mock_sleep),
        ):
            result = await check_conversation_pipeline()

        assert result.ok is False
        detail = result.detail
        assert "received" in detail
        assert "missing" in detail
        assert isinstance(detail["received"], list)
        assert isinstance(detail["missing"], list)
        assert "expression" in detail["received"]
        assert "audio_with_expression" in detail["missing"]

    @pytest.mark.asyncio
    async def test_passed_result_has_empty_missing(self):
        """Passed results have empty 'missing' list."""
        wildcard_handler: list = [None]

        mock_client = _create_mock_client(
            wildcard_handler_container=wildcard_handler,
        )

        original_sleep = asyncio.sleep

        async def _mock_sleep(duration: float) -> None:
            handler = wildcard_handler[0]
            if handler is not None:
                for event_name in sorted(EXPECTED_EVENTS):
                    await handler(event_name, {})
            await original_sleep(0)

        with (
            patch(
                "animetta.inspection.checks.pipeline.socketio.AsyncClient",
                return_value=mock_client,
            ),
            patch("animetta.inspection.checks.pipeline.asyncio.sleep", _mock_sleep),
        ):
            result = await check_conversation_pipeline()

        assert result.ok is True
        assert result.detail.get("missing") == []
        assert len(result.detail.get("received", [])) >= len(EXPECTED_EVENTS)
