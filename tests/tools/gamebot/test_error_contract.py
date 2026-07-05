"""Tests for gamebot error contracts."""

from __future__ import annotations

from animetta.tools.gamebot.contracts.errors import (
    make_process_exit_error,
    make_timeout_error,
    to_bridge_response,
)


def test_timeout_error() -> None:
    err = make_timeout_error("goto", 30.0)
    assert err.action == "goto"
    assert err.kind == "timeout"
    assert "30" in err.message


def test_process_exit_error() -> None:
    err = make_process_exit_error("status", returncode=1)
    assert err.action == "status"
    assert err.kind == "process_exit"
    assert "1" in err.message


def test_to_bridge_response_preserves_shape() -> None:
    """Adapter boundaries must return the existing bridge-style response dict."""
    err = make_timeout_error("mine", 60.0)
    resp = to_bridge_response(err)
    assert resp["status"] == "error"
    assert isinstance(resp["result"], str)
    assert "mine" in resp["result"]


def test_to_bridge_response_process_exit() -> None:
    err = make_process_exit_error("craft", returncode=-1)
    resp = to_bridge_response(err)
    assert resp["status"] == "error"
    assert "craft" in resp["result"]
