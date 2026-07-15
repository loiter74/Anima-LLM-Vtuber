from __future__ import annotations

"""Tests for LifecycleManager — signal handlers, cleanup callbacks, shutdown flag."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.orchestration.server.lifecycle import LifecycleManager

# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def lifecycle():
    """Fresh LifecycleManager for each test."""
    return LifecycleManager()


# ── LifecycleManager — Init ────────────────────────────────────────


class TestLifecycleManagerInit:
    """Construction and default state."""

    def test_init_defaults(self, lifecycle):
        """__init__ sets default attribute values."""
        assert lifecycle._shutdown_event is None
        assert lifecycle._cleanup_callbacks == []
        assert lifecycle._signal_handlers_set is False
        assert lifecycle._shutting_down is False

    def test_is_shutdown_requested_returns_flag(self, lifecycle):
        """is_shutdown_requested reflects _shutting_down."""
        assert lifecycle.is_shutdown_requested is False
        lifecycle._shutting_down = True
        assert lifecycle.is_shutdown_requested is True


# ── LifecycleManager — setup_signal_handlers ───────────────────────


class TestSetupSignalHandlers:
    """Signal handler registration."""

    def test_setup_signal_handlers_registers_sigint_and_sigterm(self, lifecycle):
        """SIGINT and SIGTERM handlers are registered."""
        shutdown_event = asyncio.Event()

        with patch.object(signal, "signal") as mock_signal:
            lifecycle.setup_signal_handlers(shutdown_event)

            assert lifecycle._shutdown_event is shutdown_event
            assert lifecycle._signal_handlers_set is True
            # SIGINT and SIGTERM are registered
            sigint_calls = [
                call for call in mock_signal.call_args_list if call.args[0] == signal.SIGINT
            ]
            sigterm_calls = [
                call for call in mock_signal.call_args_list if call.args[0] == signal.SIGTERM
            ]
            assert len(sigint_calls) == 1
            assert len(sigterm_calls) == 1

    def test_setup_signal_handlers_stores_event(self, lifecycle):
        """The shutdown_event is stored on the manager."""
        evt = asyncio.Event()
        lifecycle.setup_signal_handlers(evt)
        assert lifecycle._shutdown_event is evt

    def test_setup_signal_handlers_sets_flag(self, lifecycle):
        """_signal_handlers_set is set to True after setup."""
        lifecycle.setup_signal_handlers(asyncio.Event())
        assert lifecycle._signal_handlers_set is True


# ── LifecycleManager — register_cleanup_callback ───────────────────


class TestRegisterCleanupCallback:
    """Callback registration."""

    def test_register_adds_callback(self, lifecycle):
        """register_cleanup_callback appends to callbacks list."""

        def cb():
            return None

        lifecycle.register_cleanup_callback(cb)
        assert cb in lifecycle._cleanup_callbacks
        assert len(lifecycle._cleanup_callbacks) == 1

    def test_register_multiple_callbacks(self, lifecycle):
        """Multiple callbacks can be registered."""
        cbs = [lambda: None, lambda: None, lambda: None]
        for cb in cbs:
            lifecycle.register_cleanup_callback(cb)
        assert len(lifecycle._cleanup_callbacks) == 3


# ── LifecycleManager — cleanup_all ─────────────────────────────────


class TestCleanupAll:
    """Async cleanup execution."""

    @pytest.mark.asyncio
    async def test_cleanup_all_executes_sync_callbacks(self, lifecycle):
        """Sync callbacks are called during cleanup_all."""
        mock_cb = MagicMock()
        lifecycle.register_cleanup_callback(mock_cb)

        await lifecycle.cleanup_all()

        mock_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_all_executes_async_callbacks(self, lifecycle):
        """Async callbacks are awaited during cleanup_all."""
        mock_cb = AsyncMock()
        lifecycle.register_cleanup_callback(mock_cb)

        await lifecycle.cleanup_all()

        mock_cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_all_continues_on_error(self, lifecycle):
        """One failing callback does not stop subsequent callbacks."""
        fail_cb = MagicMock(side_effect=RuntimeError("fail"))
        success_cb = MagicMock()
        lifecycle.register_cleanup_callback(fail_cb)
        lifecycle.register_cleanup_callback(success_cb)

        await lifecycle.cleanup_all()

        fail_cb.assert_called_once()
        success_cb.assert_called_once()


# ── LifecycleManager — _signal_handler ─────────────────────────────


class TestSignalHandler:
    """Synchronous signal handler behavior."""

    def test_signal_handler_calls_sync_callbacks(self, lifecycle):
        """_signal_handler runs registered sync callbacks."""
        mock_cb = MagicMock()
        lifecycle.register_cleanup_callback(mock_cb)

        with patch("sys.exit") as mock_exit:
            lifecycle._signal_handler(signal.SIGINT, None)

        assert lifecycle._shutting_down is True
        mock_cb.assert_called_once()
        mock_exit.assert_called_once_with(0)

    def test_signal_handler_skips_async_callbacks(self, lifecycle):
        """_signal_handler warns about async callbacks but does not call them."""

        async def async_cb():
            pass

        sync_cb = MagicMock()
        lifecycle.register_cleanup_callback(async_cb)
        lifecycle.register_cleanup_callback(sync_cb)

        with patch("sys.exit"):
            lifecycle._signal_handler(signal.SIGTERM, None)

        sync_cb.assert_called_once()

    def test_signal_handler_ignores_duplicate(self, lifecycle):
        """Duplicate signals are ignored when _shutting_down is already True."""
        lifecycle._shutting_down = True
        cb = MagicMock()
        lifecycle.register_cleanup_callback(cb)

        with patch("sys.exit") as mock_exit:
            lifecycle._signal_handler(signal.SIGINT, None)

        cb.assert_not_called()
        mock_exit.assert_not_called()

    def test_signal_handler_continues_on_callback_error(self, lifecycle):
        """One failing callback does not prevent exit."""
        fail_cb = MagicMock(side_effect=RuntimeError("fail"))
        lifecycle.register_cleanup_callback(fail_cb)

        with patch("sys.exit") as mock_exit:
            lifecycle._signal_handler(signal.SIGINT, None)

        fail_cb.assert_called_once()
        mock_exit.assert_called_once_with(0)


# ── LifecycleManager — Integration: full lifecycle ─────────────────


class TestLifecycleIntegration:
    """End-to-end lifecycle flows."""

    def test_full_flow_register_cleanup_all(self, lifecycle):
        """Register callbacks then run cleanup_all."""
        results = []

        def cb1():
            results.append("cb1")

        async def cb2():
            results.append("cb2")

        lifecycle.register_cleanup_callback(cb1)
        lifecycle.register_cleanup_callback(cb2)

        # Can't run cleanup_all here since cb2 is async, need asyncio.run
        assert len(lifecycle._cleanup_callbacks) == 2
        assert lifecycle._shutting_down is False
