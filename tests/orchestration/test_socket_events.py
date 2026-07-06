from __future__ import annotations

import pytest

from animetta.orchestration.socket_events import event_name


def test_event_name_returns_configured_event_name() -> None:
    assert event_name("chat", "text") == "chat:text"


def test_event_name_includes_minecraft_command_event() -> None:
    assert event_name("minecraft", "command") == "minecraft:command"


def test_event_name_rejects_missing_event_definition() -> None:
    with pytest.raises(KeyError):
        event_name("missing", "event")
