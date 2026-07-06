from __future__ import annotations

import pytest

from animetta.orchestration.socket_events import EVENTS, event_name


def test_event_name_returns_configured_event_name() -> None:
    assert event_name("chat", "text") == "chat:text"


def test_event_name_includes_minecraft_command_event() -> None:
    assert event_name("minecraft", "command") == "minecraft:command"


def test_model_status_payload_matches_runtime_contract() -> None:
    """Catalog payload should match ModelLoadingManager and frontend store."""
    assert EVENTS["system"]["model_status"]["payload"] == {
        "service": "string",
        "name": "string",
        "status": "string",
        "error?": "string",
    }


def test_translation_configure_payload_accepts_partial_updates() -> None:
    """translation:configure supports target-language or enabled updates."""
    assert EVENTS["translation"]["configure"]["payload"] == {
        "enabled?": "boolean",
        "target_language?": "string",
    }


def test_event_name_rejects_missing_event_definition() -> None:
    with pytest.raises(KeyError):
        event_name("missing", "event")
