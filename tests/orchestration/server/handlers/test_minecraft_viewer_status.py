"""Minecraft viewer status compatibility and safety tests."""

from animetta.orchestration.server.handlers.minecraft_handlers import (
    project_viewer_status,
)


def test_projects_confirmed_following_status_to_v2_and_legacy_joined() -> None:
    payload = {
        "state": "following",
        "confirmed": True,
        "username": "LUN077",
        "target": "AnimettaBot",
        "attempt": 2,
        "reason": "viewer_joined",
    }

    status = project_viewer_status("client_viewer_status", payload)

    assert status == {
        "schema_version": 2,
        "status": "joined",
        "binding_state": "following",
        "confirmed": True,
        "username": "LUN077",
        "mode": "spectator",
        "target": "AnimettaBot",
        "attempt": 2,
        "reason": "viewer_joined",
    }


def test_projects_retry_without_leaking_raw_runtime_details() -> None:
    payload = {
        "binding_state": "degraded",
        "confirmed": False,
        "username": "LUN077",
        "target": "AnimettaBot",
        "attempt": -4,
        "retry_in_ms": 5000,
        "reason": "unbounded runtime prose",
        "error": "token=C:/private/secret",
        "commands": ["/gamemode spectator LUN077"],
        "spectate_command_sent": True,
    }

    status = project_viewer_status("client_viewer_status", payload)

    assert status == {
        "schema_version": 2,
        "status": "error",
        "binding_state": "degraded",
        "confirmed": False,
        "username": "LUN077",
        "mode": "spectator",
        "target": "AnimettaBot",
        "attempt": 0,
        "retry_in_ms": 5000,
        "reason": "unknown",
    }


def test_projects_legacy_join_event_without_v2_runtime_payload() -> None:
    assert project_viewer_status("viewer_joined", "LUN077") == {
        "schema_version": 2,
        "status": "joined",
        "binding_state": "following",
        "confirmed": True,
        "username": "LUN077",
        "mode": "spectator",
        "target": "AnimettaBot",
        "attempt": 0,
        "reason": "viewer_joined",
    }
