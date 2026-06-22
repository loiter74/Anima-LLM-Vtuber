from __future__ import annotations

"""Tests for interrupt signal handler — session-level interrupt management."""

from animetta.orchestration.graph.interrupt_handler import InterruptHandler, get_interrupt_handler


class TestInterruptHandler:
    """InterruptHandler manages per-session asyncio.Event signals."""

    # ── Singleton / Factory ─────────────────────────────────

    def test_get_interrupt_handler_returns_instance(self):
        """get_interrupt_handler() returns an InterruptHandler."""
        handler = get_interrupt_handler()
        assert isinstance(handler, InterruptHandler)

    def test_get_interrupt_handler_is_singleton(self):
        """Multiple calls return the same instance."""
        h1 = get_interrupt_handler()
        h2 = get_interrupt_handler()
        assert h1 is h2

    # ── get_signal() ────────────────────────────────────────

    def test_get_signal_creates_new_event(self):
        """First call for a session creates a new asyncio Event."""
        handler = InterruptHandler()
        event = handler.get_signal("session-1")
        assert event is not None
        assert not event.is_set()

    def test_get_signal_returns_same_event(self):
        """Repeated calls for the same session return the same event."""
        handler = InterruptHandler()
        e1 = handler.get_signal("session-1")
        e2 = handler.get_signal("session-1")
        assert e1 is e2

    def test_get_signal_different_sessions_different_events(self):
        """Different sessions get independent events."""
        handler = InterruptHandler()
        e1 = handler.get_signal("session-a")
        e2 = handler.get_signal("session-b")
        assert e1 is not e2

    # ── set_interrupt() ─────────────────────────────────────

    def test_set_interrupt_does_not_raise_for_unknown_session(self):
        """Calling set_interrupt on a session that has no signal does nothing."""
        handler = InterruptHandler()
        handler.set_interrupt("nonexistent")  # should not raise

    def test_set_interrupt_triggers_event(self):
        """After set_interrupt, the session interrupt is flagged."""
        handler = InterruptHandler()
        handler.get_signal("session-1")
        handler.set_interrupt("session-1")
        assert handler._signals["session-1"].is_set()

    def test_set_interrupt_only_affects_target_session(self):
        """Interrupting one session does not affect another."""
        handler = InterruptHandler()
        handler.get_signal("session-a")
        handler.get_signal("session-b")

        handler.set_interrupt("session-a")

        assert handler._signals["session-a"].is_set()
        assert not handler._signals["session-b"].is_set()

    # ── clear_interrupt() ───────────────────────────────────

    def test_clear_interrupt_does_not_raise_for_unknown_session(self):
        """Calling clear_interrupt on a non-existent session is safe."""
        handler = InterruptHandler()
        handler.clear_interrupt("nonexistent")  # should not raise

    def test_clear_interrupt_resets_event(self):
        """After clear_interrupt, the interrupt flag is cleared."""
        handler = InterruptHandler()
        handler.get_signal("session-1")
        handler.set_interrupt("session-1")
        assert handler._signals["session-1"].is_set()

        handler.clear_interrupt("session-1")
        assert not handler._signals["session-1"].is_set()

    def test_clear_interrupt_on_unset_event(self):
        """Clearing an already-clear event does not raise."""
        handler = InterruptHandler()
        handler.get_signal("session-1")
        handler.clear_interrupt("session-1")  # no-op, should be safe
        assert not handler._signals["session-1"].is_set()

    # ── is_interrupted() ────────────────────────────────────

    def test_is_interrupted_returns_false_by_default(self):
        """A session that was never interrupted returns False."""
        handler = InterruptHandler()
        handler.get_signal("session-1")
        assert not handler.is_interrupted("session-1")

    def test_is_interrupted_returns_true_after_set(self):
        """After set_interrupt, is_interrupted returns True."""
        handler = InterruptHandler()
        handler.get_signal("session-1")
        handler.set_interrupt("session-1")
        assert handler.is_interrupted("session-1")

    def test_is_interrupted_returns_false_after_clear(self):
        """After set then clear, is_interrupted returns False."""
        handler = InterruptHandler()
        handler.get_signal("session-1")
        handler.set_interrupt("session-1")
        handler.clear_interrupt("session-1")
        assert not handler.is_interrupted("session-1")

    def test_is_interrupted_returns_false_for_unknown_session(self):
        """A session that was never registered returns False."""
        handler = InterruptHandler()
        assert not handler.is_interrupted("unknown")

    # ── remove_session() ────────────────────────────────────

    def test_remove_session_removes_signal(self):
        """After remove_session, the signal dict entry is gone."""
        handler = InterruptHandler()
        handler.get_signal("session-1")
        assert "session-1" in handler._signals

        handler.remove_session("session-1")
        assert "session-1" not in handler._signals

    def test_remove_session_does_not_raise_for_unknown(self):
        """Removing a non-existent session is safe."""
        handler = InterruptHandler()
        handler.remove_session("nonexistent")  # should not raise

    def test_remove_session_cleans_up_is_interrupted(self):
        """After remove, is_interrupted returns False (no signal found)."""
        handler = InterruptHandler()
        handler.get_signal("session-1")
        handler.set_interrupt("session-1")
        handler.remove_session("session-1")
        assert not handler.is_interrupted("session-1")

    # ── Full lifecycle ──────────────────────────────────────

    def test_full_lifecycle(self):
        """End-to-end: create, interrupt, check, clear, remove."""
        handler = InterruptHandler()

        # Session A lifecycle
        handler.get_signal("session-a")
        assert not handler.is_interrupted("session-a")

        handler.set_interrupt("session-a")
        assert handler.is_interrupted("session-a")

        handler.clear_interrupt("session-a")
        assert not handler.is_interrupted("session-a")

        handler.remove_session("session-a")
        assert not handler.is_interrupted("session-a")

    def test_multiple_sessions_independent(self):
        """Multiple sessions can be interrupted independently."""
        handler = InterruptHandler()

        for sid in ("alpha", "beta", "gamma"):
            handler.get_signal(sid)

        handler.set_interrupt("beta")

        assert not handler.is_interrupted("alpha")
        assert handler.is_interrupted("beta")
        assert not handler.is_interrupted("gamma")

        handler.clear_interrupt("beta")
        assert not handler.is_interrupted("beta")
