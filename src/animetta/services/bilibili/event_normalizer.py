"""Normalize decoded Bilibili commands without retaining raw payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .models import LivestreamEvent, LivestreamEventType


def normalize_bilibili_event(
    command: str,
    raw_event: Mapping[str, Any],
    *,
    sequence: int,
    offset_ms: int,
) -> LivestreamEvent:
    """Convert one decoded Bilibili command to the stable event contract."""
    if command == "DANMU_MSG":
        data = _mapping(raw_event.get("data"))
        info = data.get("info", [])
        text = str(info[1]) if len(info) > 1 else ""
        user = info[2] if len(info) > 2 and isinstance(info[2], list) else []
        user_id = user[0] if len(user) > 0 else 0
        user_name = str(user[1]) if len(user) > 1 else ""
        return _event(
            sequence,
            offset_ms,
            LivestreamEventType.DANMAKU,
            actor_id=user_name,
            text=text,
            payload={"user_id": user_id},
        )

    data = _nested_data(raw_event)
    if command == "SEND_GIFT":
        user_name = str(data.get("uname", "未知"))
        gift_name = str(data.get("giftName", "礼物"))
        gift_num = int(data.get("num", 1) or 1)
        return _event(
            sequence,
            offset_ms,
            LivestreamEventType.GIFT,
            actor_id=user_name,
            text=f"感谢 {user_name} 送出的 {gift_num} 个 {gift_name}",
            payload={
                "user_id": data.get("uid", 0),
                "gift_name": gift_name,
                "gift_num": gift_num,
            },
        )

    if command == "SUPER_CHAT_MESSAGE":
        user_info = _mapping(data.get("user_info"))
        user_name = str(user_info.get("uname", "未知"))
        price = data.get("price", 0)
        message = str(data.get("message", ""))
        return _event(
            sequence,
            offset_ms,
            LivestreamEventType.SUPER_CHAT,
            actor_id=user_name,
            text=f"SC ¥{price}: {message}",
            payload={"user_id": data.get("uid", 0), "price": price},
        )

    if command == "INTERACT_WORD_V2":
        decoded = _mapping(data.get("pb_decoded"))
        msg_type = decoded.get("msg_type")
        event_type = {
            1: LivestreamEventType.ENTER,
            2: LivestreamEventType.FOLLOW,
        }.get(msg_type)
        if event_type is not None:
            return _event(
                sequence,
                offset_ms,
                event_type,
                actor_id=str(decoded.get("uname", "")),
                payload={"user_id": decoded.get("uid", 0)},
            )

    if command in {"LIKE_INFO_V3_CLICK", "LIKE_INFO_V3_UPDATE"}:
        count = data.get("like_count", data.get("click_count", 1))
        payload: dict[str, Any] = {"count": int(count or 0)}
        user_id = data.get("uid")
        if user_id is not None:
            payload = {"user_id": user_id, **payload}
        return _event(
            sequence,
            offset_ms,
            LivestreamEventType.LIKE_BATCH,
            actor_id=str(data.get("uname", "")),
            payload=payload,
        )

    if command in {"VIEW", "WATCHED_CHANGE"}:
        raw_data = raw_event.get("data")
        if isinstance(raw_data, Mapping):
            view_data = _nested_data(raw_event)
            popularity = view_data.get("num", view_data.get("count", 0))
        else:
            popularity = raw_data or 0
        return _event(
            sequence,
            offset_ms,
            LivestreamEventType.POPULARITY_SNAPSHOT,
            payload={"popularity": int(popularity)},
        )

    if command in {"VERIFICATION_SUCCESSFUL", "DISCONNECT"}:
        connected = command == "VERIFICATION_SUCCESSFUL"
        return _event(
            sequence,
            offset_ms,
            LivestreamEventType.CONNECTION_STATE,
            payload={
                "connected": connected,
                "message": "Connected" if connected else "Disconnected",
            },
        )

    if command in {"LIVE", "PREPARING"}:
        is_live = command == "LIVE"
        return _event(
            sequence,
            offset_ms,
            LivestreamEventType.BROADCAST_STATE,
            payload={
                "live": is_live,
                "message": "Live" if is_live else "Waiting for broadcast",
            },
        )

    safe_command = re.sub(r"[^A-Z0-9_]", "_", command.upper())[:64]
    return _event(
        sequence,
        offset_ms,
        LivestreamEventType.UNKNOWN,
        payload={"command": safe_command},
    )


def _event(
    sequence: int,
    offset_ms: int,
    event_type: LivestreamEventType,
    *,
    actor_id: str = "",
    text: str = "",
    payload: dict[str, Any] | None = None,
) -> LivestreamEvent:
    return LivestreamEvent(
        sequence=sequence,
        offset_ms=offset_ms,
        event_type=event_type,
        actor_id=actor_id,
        text=text,
        payload=payload or {},
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested_data(raw_event: Mapping[str, Any]) -> Mapping[str, Any]:
    outer = _mapping(raw_event.get("data"))
    return _mapping(outer.get("data", outer))
