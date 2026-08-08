from __future__ import annotations

import pytest

from animetta.orchestration.socket_events import EVENTS, event_name


def test_event_name_returns_configured_event_name() -> None:
    assert event_name("chat", "text") == "chat:text"


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


def test_config_switch_payload_matches_handler_contract() -> None:
    """config:switch should document the active field and legacy fallback."""
    assert EVENTS["config"]["switch"]["payload"] == {
        "config_name?": "string",
        "file?": "string",
    }
    assert EVENTS["config"]["switched"]["payload"] == {
        "type?": "string",
        "config_name": "string",
        "message": "string",
    }


def test_config_log_level_changed_payload_matches_handler_contract() -> None:
    """config:log_level_changed should document the emitted response shape."""
    assert EVENTS["config"]["log_level_changed"]["payload"] == {
        "type?": "string",
        "success": "boolean",
        "level": "string",
        "message": "string",
    }


def test_persona_updated_payload_matches_runtime_contract() -> None:
    """persona:updated should match PersonaHandlers and the frontend store."""
    assert EVENTS["persona"]["updated"]["payload"] == {
        "persona_name": "string",
        "mbti?": "object",
    }


def test_persona_personality_updated_payload_matches_handler_contract() -> None:
    """persona:personality_updated should document the emitted mode response."""
    assert EVENTS["persona"]["personality_updated"]["payload"] == {
        "mode": "string",
    }


def test_event_name_rejects_missing_event_definition() -> None:
    with pytest.raises(KeyError):
        event_name("missing", "event")
