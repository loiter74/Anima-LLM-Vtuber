"""Real Socket.IO contract checks for canonical and legacy chat ingress."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import socketio

URL = "http://localhost:12394"
IDENTITY_KEYS = {"message_id", "conversation_id", "task_id", "turn_id"}


@pytest.mark.parametrize(
    ("ingress", "sentence_event", "control_event"),
    [
        ("chat:text", "chat:sentence", "chat:control"),
        ("text_input", "sentence", "control"),
    ],
)
@pytest.mark.asyncio
async def test_real_socket_chat_selects_one_correlated_contract(
    server, ingress: str, sentence_event: str, control_event: str
) -> None:
    del server
    client = socketio.AsyncClient(reconnection=False)
    received: dict[str, list[dict]] = {}
    terminal = asyncio.Event()

    @client.on("*")
    async def capture(event: str, payload: dict | None = None) -> None:
        if isinstance(payload, dict):
            received.setdefault(event, []).append(payload)
            if event == control_event and payload.get("signal") == "conversation-end":
                terminal.set()
            if event in {"system:error", "error"} and payload.get("terminal"):
                terminal.set()

    message_id = str(uuid4())
    conversation_id = str(uuid4())
    task_id = str(uuid4())
    payload = (
        {
            "text": "请用一句话介绍你自己。",
            "message_id": message_id,
            "conversation_id": conversation_id,
            "task_id": task_id,
            "turn_id": task_id,
            "source": "text",
            "is_inspection": False,
            "is_acceptance": True,
        }
        if ingress == "chat:text"
        else {"text": "请用一句话介绍你自己。"}
    )

    await client.connect(URL, transports=["websocket"], wait_timeout=10)
    try:
        await client.emit(ingress, payload)
        await asyncio.wait_for(terminal.wait(), timeout=60)
    finally:
        await client.disconnect()

    opposite_sentence = "sentence" if sentence_event == "chat:sentence" else "chat:sentence"
    opposite_control = "control" if control_event == "chat:control" else "chat:control"
    assert received.get(sentence_event), received
    assert opposite_sentence not in received
    assert opposite_control not in received
    assert (
        len(
            [
                event
                for event in received.get(sentence_event, [])
                if event.get("is_complete") or event.get("text") == ""
            ]
        )
        == 1
    )

    correlated = [
        item
        for event, items in received.items()
        if event not in {"system:connection_established"}
        for item in items
        if item.keys() >= IDENTITY_KEYS
    ]
    assert correlated
    resolved = {tuple(item[key] for key in sorted(IDENTITY_KEYS)) for item in correlated}
    assert len(resolved) == 1
    resolved_identity = correlated[0]
    assert resolved_identity["turn_id"] == resolved_identity["task_id"]
    if ingress == "chat:text":
        assert resolved_identity["message_id"] == message_id
        assert resolved_identity["conversation_id"] == conversation_id
        assert resolved_identity["task_id"] == task_id
