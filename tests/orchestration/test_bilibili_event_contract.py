"""Bilibili Socket.IO catalog contracts."""

from animetta.orchestration.socket_events import EVENTS


def test_bilibili_status_catalog_is_additive_and_structured() -> None:
    payload = EVENTS["bilibili"]["danmaku_status"]["payload"]

    assert payload == {
        "state": "string",
        "connected": "boolean",
        "room_id": "number|null",
        "desired_room_id": "number|null",
        "retry_count": "number",
        "error_code": "string|null",
        "generation_id": "number",
        "message": "string",
        "updated_at": "number",
    }


def test_bilibili_control_commands_declare_typed_acknowledgments() -> None:
    expected = {
        "accepted": "boolean",
        "state": "string",
        "error_code": "string|null",
        "message": "string",
    }

    for action in ("connect", "disconnect", "update_room"):
        assert EVENTS["bilibili"][action]["ack"] == expected
        assert EVENTS["bilibili"][action]["payload"]["expected_generation_id?"] == "number"


def test_bilibili_live_event_catalog_preserves_normalized_event_identity() -> None:
    assert EVENTS["bilibili"]["live_event"] == {
        "name": "bilibili:live_event",
        "payload": {
            "room_id": "number",
            "generation_id": "number",
            "sequence": "number",
            "offset_ms": "number",
            "event_type": "string",
            "actor_id": "string",
            "text": "string",
            "payload": "object",
        },
    }
