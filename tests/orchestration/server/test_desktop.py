from __future__ import annotations

"""Tests for DesktopClientManager — client registration, type queries, connection tracking."""


import pytest

from animetta.orchestration.server.desktop import DESKTOP_CLIENT_TYPES, DesktopClientManager

# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def manager():
    """Fresh DesktopClientManager for each test."""
    return DesktopClientManager()


# ── DesktopClientManager — Init ────────────────────────────────────


class TestDesktopClientManagerInit:
    """Construction and default state."""

    def test_init_creates_empty_clients(self, manager):
        """__init__ creates empty clients dict."""
        assert manager.clients == {}

    def test_client_count_zero(self, manager):
        """Initial client_count is 0."""
        assert manager.client_count == 0

    def test_desktop_client_types_defined(self):
        """DESKTOP_CLIENT_TYPES contains expected types."""
        assert "live2d" in DESKTOP_CLIENT_TYPES
        assert "chat" in DESKTOP_CLIENT_TYPES
        assert "web" in DESKTOP_CLIENT_TYPES
        assert len(DESKTOP_CLIENT_TYPES) == 3


# ── DesktopClientManager — register ────────────────────────────────


class TestRegister:
    """Client registration."""

    def test_register_valid_type(self, manager):
        """Register a valid client type returns True."""
        result = manager.register("sid_live2d", "live2d")
        assert result is True
        assert "sid_live2d" in manager.clients
        assert manager.clients["sid_live2d"]["client_type"] == "live2d"
        assert manager.clients["sid_live2d"]["connected"] is True

    def test_register_chat_type(self, manager):
        """Register a chat client."""
        result = manager.register("sid_chat", "chat")
        assert result is True
        assert manager.clients["sid_chat"]["client_type"] == "chat"

    def test_register_web_type(self, manager):
        """Register a web client."""
        result = manager.register("sid_web", "web")
        assert result is True
        assert manager.clients["sid_web"]["client_type"] == "web"

    def test_register_invalid_type(self, manager):
        """Register an unknown client type returns False."""
        result = manager.register("sid_bad", "mobile")
        assert result is False
        assert "sid_bad" not in manager.clients

    def test_register_default_type(self, manager):
        """Register without type defaults to 'web'."""
        result = manager.register("sid_default")
        assert result is True
        assert manager.clients["sid_default"]["client_type"] == "web"

    def test_register_multiple_clients(self, manager):
        """Multiple clients can be registered."""
        assert manager.register("sid1", "live2d") is True
        assert manager.register("sid2", "chat") is True
        assert manager.register("sid3", "web") is True
        assert manager.client_count == 3

    def test_register_increments_count(self, manager):
        """client_count increases with each registration."""
        assert manager.client_count == 0
        manager.register("sid1", "live2d")
        assert manager.client_count == 1
        manager.register("sid2", "chat")
        assert manager.client_count == 2


# ── DesktopClientManager — unregister ──────────────────────────────


class TestUnregister:
    """Client unregistration."""

    def test_unregister_removes_client(self, manager):
        """Unregister removes the client entry."""
        manager.register("sid1", "live2d")
        manager.unregister("sid1")
        assert "sid1" not in manager.clients

    def test_unregister_unknown_sid(self, manager):
        """Unregister with unknown sid does nothing."""
        manager.unregister("nonexistent")
        assert manager.client_count == 0

    def test_unregister_decrements_count(self, manager):
        """client_count decreases after unregister."""
        manager.register("sid1", "live2d")
        manager.register("sid2", "chat")
        assert manager.client_count == 2
        manager.unregister("sid1")
        assert manager.client_count == 1
        manager.unregister("sid2")
        assert manager.client_count == 0


# ── DesktopClientManager — get_clients_by_type ─────────────────────


class TestGetClientsByType:
    """Type-based client queries."""

    def test_returns_correct_sids(self, manager):
        """get_clients_by_type returns only matching, connected clients."""
        manager.register("l1", "live2d")
        manager.register("l2", "live2d")
        manager.register("c1", "chat")

        live2d_sids = manager.get_clients_by_type("live2d")
        assert live2d_sids == {"l1", "l2"}

        chat_sids = manager.get_clients_by_type("chat")
        assert chat_sids == {"c1"}

    def test_excludes_disconnected_clients(self, manager):
        """Disconnected clients are not returned by get_clients_by_type."""
        manager.register("l1", "live2d")
        manager.register("l2", "live2d")
        manager.set_connected("l2", False)

        live2d_sids = manager.get_clients_by_type("live2d")
        assert live2d_sids == {"l1"}

    def test_returns_empty_set_for_unknown_type(self, manager):
        """Unknown type returns empty set."""
        result = manager.get_clients_by_type("nonexistent")
        assert result == set()

    def test_returns_empty_set_when_none_registered(self, manager):
        """No clients returns empty set."""
        assert manager.get_clients_by_type("live2d") == set()
        assert manager.get_clients_by_type("chat") == set()


# ── DesktopClientManager — connection state ────────────────────────


class TestConnectionState:
    """Client connected/disconnected state management."""

    def test_is_connected_returns_true_for_registered(self, manager):
        """is_connected returns True for a registered client."""
        manager.register("sid1", "live2d")
        assert manager.is_connected("sid1") is True

    def test_is_connected_returns_false_for_unknown(self, manager):
        """is_connected returns False for unregistered SIDs."""
        assert manager.is_connected("unknown") is False

    def test_set_connected_false(self, manager):
        """set_connected to False is reflected by is_connected."""
        manager.register("sid1", "live2d")
        manager.set_connected("sid1", False)
        assert manager.is_connected("sid1") is False

    def test_set_connected_true(self, manager):
        """set_connected to True is reflected."""
        manager.register("sid1", "live2d")
        manager.set_connected("sid1", False)
        manager.set_connected("sid1", True)
        assert manager.is_connected("sid1") is True

    def test_set_connected_unknown_sid(self, manager):
        """set_connected on unknown sid does nothing."""
        manager.set_connected("unknown", False)  # Should not raise


# ── DesktopClientManager — get_client_type ─────────────────────────


class TestGetClientType:
    """Individual client type queries."""

    def test_get_client_type_returns_type(self, manager):
        """get_client_type returns the stored type."""
        manager.register("sid1", "live2d")
        assert manager.get_client_type("sid1") == "live2d"

    def test_get_client_type_defaults_to_web(self, manager):
        """get_client_type returns 'web' for unknown SIDs."""
        assert manager.get_client_type("unknown") == "web"

    def test_get_client_type_default_for_untyped(self, manager):
        """get_client_type returns 'web' for registered client without explicit type."""
        manager.clients["test"] = {"client_type": "unknown"}
        assert manager.get_client_type("test") == "unknown"


# ── DesktopClientManager — Integration ─────────────────────────────


class TestIntegration:
    """Multi-step workflows."""

    def test_full_lifecycle(self, manager):
        """Register, check state, unregister."""
        # Register
        assert manager.register("sid1", "live2d") is True
        assert manager.client_count == 1
        assert manager.is_connected("sid1") is True
        assert manager.get_client_type("sid1") == "live2d"

        # Disconnect
        manager.set_connected("sid1", False)
        assert manager.is_connected("sid1") is False
        assert manager.get_clients_by_type("live2d") == set()

        # Reconnect
        manager.set_connected("sid1", True)
        assert manager.is_connected("sid1") is True
        assert manager.get_clients_by_type("live2d") == {"sid1"}

        # Unregister
        manager.unregister("sid1")
        assert manager.client_count == 0
        assert manager.get_clients_by_type("live2d") == set()

    def test_multiple_sids_same_type(self, manager):
        """Multiple SIDs of the same type are all tracked."""
        for i in range(5):
            manager.register(f"sid_{i}", "live2d")
        assert manager.client_count == 5
        assert len(manager.get_clients_by_type("live2d")) == 5

    def test_mixed_types_counts(self, manager):
        """Different types are counted correctly."""
        manager.register("l1", "live2d")
        manager.register("l2", "live2d")
        manager.register("c1", "chat")
        assert manager.client_count == 3
        assert len(manager.get_clients_by_type("live2d")) == 2
        assert len(manager.get_clients_by_type("chat")) == 1
        assert len(manager.get_clients_by_type("web")) == 0
