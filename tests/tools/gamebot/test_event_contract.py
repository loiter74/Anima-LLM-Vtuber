"""Tests for gamebot event contracts."""

from __future__ import annotations

import json

from animetta.tools.gamebot.contracts.events import (
    KNOWN_EVENT_TYPES,
    GameBotEvent,
    parse_event_from_response_line,
)

# --- Known events ---


def test_known_login_event() -> None:
    event = GameBotEvent(type="login", payload={"username": "AnimettaBot"})
    assert event.type == "login"
    assert event.payload["username"] == "AnimettaBot"


def test_known_spawn_event() -> None:
    event = GameBotEvent(type="spawn", payload={})
    assert event.type == "spawn"


def test_known_heartbeat_event() -> None:
    event = GameBotEvent(
        type="heartbeat",
        payload={"health": 20.0, "food": 18, "position": {"x": 100, "y": 64, "z": -50}},
    )
    assert event.type == "heartbeat"
    assert event.payload["health"] == 20.0


def test_known_event_types_cover_protocol() -> None:
    """Verify KNOWN_EVENT_TYPES includes all protocol-level events."""
    for expected in ["login", "spawn", "heartbeat", "disconnect", "initial_loadout",
                     "viewer_joined", "viewer_left", "client_viewer_status"]:
        assert expected in KNOWN_EVENT_TYPES, f"Missing known event type: {expected}"


# --- Unknown events ---


def test_unknown_event_preserved() -> None:
    """Unknown event types must be preserved as metadata, not rejected."""
    event = GameBotEvent(type="some_new_feature", payload={"data": 42})
    assert event.type == "some_new_feature"
    assert event.payload == {"data": 42}


def test_unknown_event_does_not_raise() -> None:
    """Must not raise on unknown event types — forward-compatible."""
    event = GameBotEvent(type="completely_unknown_event_12345", payload={})
    assert event.type == "completely_unknown_event_12345"


# --- Parsing from JSON line ---


def test_parse_event_from_response_line_success() -> None:
    line = json.dumps({"id": None, "status": "event", "result": {"type": "login", "username": "Bot"}})
    event = parse_event_from_response_line(line)
    assert event is not None
    assert event.type == "login"
    assert event.payload["username"] == "Bot"


def test_parse_event_from_response_line_not_event() -> None:
    """Lines with a real id or non-event status should return None."""
    line = json.dumps({"id": 1, "status": "success", "result": "ok"})
    assert parse_event_from_response_line(line) is None


def test_parse_event_from_response_line_malformed_json() -> None:
    """Malformed JSON should return None, not crash."""
    assert parse_event_from_response_line("not json {{{") is None


def test_parse_event_from_response_line_missing_type() -> None:
    """Event result without type field should return None."""
    line = json.dumps({"id": None, "status": "event", "result": {"data": 123}})
    assert parse_event_from_response_line(line) is None
