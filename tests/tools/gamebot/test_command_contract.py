"""Tests for gamebot command and response contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from animetta.tools.gamebot.contracts.commands import (
    GameBotCommandRequest,
    GameBotCommandResponse,
    seconds_to_ms,
)

# --- Command Request ---


def test_command_request_preserves_fields() -> None:
    req = GameBotCommandRequest(id=1, action="status", params={}, timeout_ms=5000)
    assert req.id == 1
    assert req.action == "status"
    assert req.params == {}
    assert req.timeout_ms == 5000


def test_command_request_with_params() -> None:
    req = GameBotCommandRequest(
        id=42, action="goto", params={"x": 10, "y": 64, "z": -20}, timeout_ms=30000
    )
    assert req.id == 42
    assert req.action == "goto"
    assert req.params == {"x": 10, "y": 64, "z": -20}
    assert req.timeout_ms == 30000


def test_command_request_serializes_to_json_line() -> None:
    req = GameBotCommandRequest(
        id=1, action="mine", params={"block_type": "stone", "count": 3}, timeout_ms=60000
    )
    data = req.model_dump()
    assert data["id"] == 1
    assert data["action"] == "mine"
    assert data["params"]["block_type"] == "stone"
    assert data["timeout_ms"] == 60000


# --- Seconds to ms helper ---


def test_seconds_to_ms_converts_correctly() -> None:
    assert seconds_to_ms(5.0) == 5000
    assert seconds_to_ms(0.5) == 500
    assert seconds_to_ms(60) == 60000
    assert seconds_to_ms(0) == 0


def test_seconds_to_ms_negative_raises() -> None:
    with pytest.raises(ValueError):
        seconds_to_ms(-1.0)


# --- Command Response ---


def test_command_response_preserves_shape() -> None:
    resp = GameBotCommandResponse(id=1, status="success", result={"ok": True})
    assert resp.id == 1
    assert resp.status == "success"
    assert resp.result == {"ok": True}


def test_command_response_error() -> None:
    resp = GameBotCommandResponse(id=5, status="error", result="timed out")
    assert resp.id == 5
    assert resp.status == "error"
    assert resp.result == "timed out"


def test_command_response_event() -> None:
    resp = GameBotCommandResponse(
        id=None, status="event", result={"type": "login", "username": "Bot"}
    )
    assert resp.id is None
    assert resp.status == "event"


def test_command_response_invalid_status_rejected() -> None:
    with pytest.raises(ValidationError):
        GameBotCommandResponse(id=1, status="pending", result={})


def test_command_response_result_any_type() -> None:
    """Result can be str, dict, list, None — matches existing bridge behavior."""
    r1 = GameBotCommandResponse(id=1, status="success", result="ok")
    r2 = GameBotCommandResponse(id=2, status="success", result={"data": 1})
    r3 = GameBotCommandResponse(id=3, status="success", result=[1, 2, 3])
    r4 = GameBotCommandResponse(id=4, status="success", result=None)
    assert r1.result == "ok"
    assert r2.result == {"data": 1}
    assert r3.result == [1, 2, 3]
    assert r4.result is None
