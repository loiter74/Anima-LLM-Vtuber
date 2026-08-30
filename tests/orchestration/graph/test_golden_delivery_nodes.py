from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.types import RunnableConfig

from animetta.orchestration.graph.delivery_nodes import (
    conversation_start_node,
    performance_output_node,
    reply_output_node,
)
from animetta.orchestration.graph.media_status import MediaStatus
from animetta.orchestration.graph.state import create_initial_state
from animetta.orchestration.graph.tts_node import tts_node
from animetta.services.bilibili.reply_media import (
    BroadcastMediaArbiter,
    BroadcastMediaTurn,
    bind_reply_media_turn,
)


def state():
    result = create_initial_state("session", user_text="你好")
    result["response_text"] = "旅人，晚上好。"
    result["emotion"] = "happy"
    return result


def emitted(socket: AsyncMock) -> list[tuple[str, dict]]:
    return [(call.args[0], call.args[1]) for call in socket.emit.await_args_list]


@pytest.mark.asyncio
async def test_start_and_final_text_are_emitted_before_qwen_completes() -> None:
    socket = AsyncMock()
    release = asyncio.Event()

    async def synthesize(text: str) -> bytes:
        await release.wait()
        return b"RIFFaudio"

    context = SimpleNamespace(
        tts_engine=SimpleNamespace(synthesize=synthesize),
        config=SimpleNamespace(
            system=SimpleNamespace(runtime_profile="golden", golden_tts_timeout_seconds=20.0)
        ),
    )
    config = RunnableConfig(configurable={"socketio": socket, "service_context": context})
    current = state()

    await conversation_start_node(current, config)
    await reply_output_node(current, config)
    tts_task = asyncio.create_task(tts_node(current, config))
    await asyncio.sleep(0)

    events_before_tts = emitted(socket)
    assert events_before_tts[0][0] == "chat:control"
    assert events_before_tts[0][1]["signal"] == "conversation-start"
    assert [event for event, _ in events_before_tts].count("chat:sentence") == 2
    assert not tts_task.done()

    release.set()
    current.update(await tts_task)
    await performance_output_node(current, config)
    events = emitted(socket)
    assert events[-1][0] == "chat:control"
    assert events[-1][1]["signal"] == "conversation-end"


@pytest.mark.asyncio
async def test_degraded_media_keeps_live2d_and_emits_no_audio() -> None:
    socket = AsyncMock()
    current = state()
    current["tts_audio"] = None
    current["media_status"] = MediaStatus("degraded", "timeout", "Qwen3TTSTTS", True)
    await performance_output_node(current, RunnableConfig(configurable={"socketio": socket}))
    events = emitted(socket)
    names = [event for event, _ in events]
    assert "chat:expression" in names
    assert "chat:live2d_action" not in names
    assert "chat:audio_with_expression" not in names
    degradation = next(
        payload
        for event, payload in events
        if event == "chat:control" and payload.get("type") == "media-degraded"
    )
    assert degradation["reason"] == "timeout"
    assert degradation["retryable"] is True
    assert events[-1][1]["signal"] == "conversation-end"


@pytest.mark.asyncio
async def test_every_phase_uses_the_same_identity() -> None:
    socket = AsyncMock()
    current = state()
    current["media_status"] = MediaStatus("skipped", "no_audio")
    config = RunnableConfig(configurable={"socketio": socket})
    await conversation_start_node(current, config)
    await reply_output_node(current, config)
    await performance_output_node(current, config)
    identities = {
        (payload["message_id"], payload["conversation_id"], payload["task_id"], payload["turn_id"])
        for _, payload in emitted(socket)
    }
    assert len(identities) == 1


@pytest.mark.asyncio
async def test_empty_response_never_acquires_the_media_turn() -> None:
    socket = AsyncMock()
    current = state()
    current["response_text"] = ""
    on_acquired = AsyncMock()
    turn = BroadcastMediaTurn(
        BroadcastMediaArbiter(),
        priority=50,
        on_acquired=on_acquired,
    )

    with bind_reply_media_turn(turn):
        result = await reply_output_node(
            current,
            RunnableConfig(configurable={"socketio": socket}),
        )

    assert result == {"error": "No authored response"}
    on_acquired.assert_not_awaited()
    socket.emit.assert_not_awaited()
    await turn.finish()
