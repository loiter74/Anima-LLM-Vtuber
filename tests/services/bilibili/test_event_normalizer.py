from __future__ import annotations

import json
from pathlib import Path

import pytest

from animetta.services.bilibili.event_normalizer import normalize_bilibili_event
from animetta.services.bilibili.models import LivestreamEventType


@pytest.mark.parametrize(
    ("command", "raw_event", "event_type", "actor_id", "text", "payload"),
    [
        (
            "DANMU_MSG",
            {"data": {"info": [None, "你好？", [42, "alice"]]}},
            LivestreamEventType.DANMAKU,
            "alice",
            "你好？",
            {"user_id": 42},
        ),
        (
            "SEND_GIFT",
            {
                "data": {
                    "data": {
                        "uid": 43,
                        "uname": "bob",
                        "giftName": "小花花",
                        "num": 2,
                    }
                }
            },
            LivestreamEventType.GIFT,
            "bob",
            "感谢 bob 送出的 2 个 小花花",
            {"user_id": 43, "gift_name": "小花花", "gift_num": 2},
        ),
        (
            "SUPER_CHAT_MESSAGE",
            {
                "data": {
                    "data": {
                        "uid": 44,
                        "message": "加油",
                        "price": 30,
                        "user_info": {"uname": "carol"},
                    }
                }
            },
            LivestreamEventType.SUPER_CHAT,
            "carol",
            "SC ¥30: 加油",
            {"user_id": 44, "price": 30},
        ),
        (
            "INTERACT_WORD_V2",
            {"data": {"data": {"pb_decoded": {"uid": 45, "uname": "dora", "msg_type": 1}}}},
            LivestreamEventType.ENTER,
            "dora",
            "",
            {"user_id": 45},
        ),
        (
            "INTERACT_WORD_V2",
            {"data": {"data": {"pb_decoded": {"uid": 46, "uname": "erin", "msg_type": 2}}}},
            LivestreamEventType.FOLLOW,
            "erin",
            "",
            {"user_id": 46},
        ),
        (
            "LIKE_INFO_V3_CLICK",
            {"data": {"data": {"uid": 47, "uname": "frank", "like_count": 1}}},
            LivestreamEventType.LIKE_BATCH,
            "frank",
            "",
            {"user_id": 47, "count": 1},
        ),
        (
            "LIKE_INFO_V3_UPDATE",
            {"data": {"data": {"click_count": 88}}},
            LivestreamEventType.LIKE_BATCH,
            "",
            "",
            {"count": 88},
        ),
        (
            "VIEW",
            {"data": 1234},
            LivestreamEventType.POPULARITY_SNAPSHOT,
            "",
            "",
            {"popularity": 1234},
        ),
        (
            "VERIFICATION_SUCCESSFUL",
            {},
            LivestreamEventType.CONNECTION_STATE,
            "",
            "",
            {"connected": True, "message": "Connected"},
        ),
        (
            "LIVE",
            {"data": {"roomid": 123}},
            LivestreamEventType.BROADCAST_STATE,
            "",
            "",
            {"live": True, "message": "Live"},
        ),
        (
            "PREPARING",
            {"data": {"roomid": 123}},
            LivestreamEventType.BROADCAST_STATE,
            "",
            "",
            {"live": False, "message": "Waiting for broadcast"},
        ),
    ],
)
def test_normalizes_supported_bilibili_events(
    command: str,
    raw_event: dict,
    event_type: LivestreamEventType,
    actor_id: str,
    text: str,
    payload: dict,
) -> None:
    event = normalize_bilibili_event(
        command,
        raw_event,
        sequence=9,
        offset_ms=250,
    )

    assert event.sequence == 9
    assert event.offset_ms == 250
    assert event.event_type is event_type
    assert event.actor_id == actor_id
    assert event.text == text
    assert event.payload == payload


def test_unknown_command_does_not_retain_raw_payload() -> None:
    event = normalize_bilibili_event(
        "FUTURE-COMMAND!",
        {"data": {"uid": 9988, "token": "secret"}},
        sequence=10,
        offset_ms=500,
    )

    assert event.event_type is LivestreamEventType.UNKNOWN
    assert event.actor_id == ""
    assert event.text == ""
    assert event.payload == {"command": "FUTURE_COMMAND_"}
    assert "9988" not in repr(event)
    assert "secret" not in repr(event)


@pytest.mark.parametrize(
    "fixture",
    json.loads(
        (Path(__file__).parents[2] / "fixtures" / "bilibili" / "protocol_events.json").read_text(
            encoding="utf-8"
        ),
    ),
)
def test_locked_protocol_fixture_maps_without_raw_payload(fixture: dict[str, object]) -> None:
    normalized = normalize_bilibili_event(
        str(fixture["command"]),
        fixture["raw"],
        sequence=0,
        offset_ms=0,
    )

    assert normalized.event_type.value == fixture["expected_type"]
    assert "room_id" not in normalized.payload
    assert "secret" not in normalized.payload
