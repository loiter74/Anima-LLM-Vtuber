from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from animetta.config import ReplyPolicyConfig
from animetta.orchestration.graph.checkpointing import CheckpointRequest
from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator
from animetta.orchestration.server.handlers.bilibili_handlers import BilibiliHandlers
from animetta.services.bilibili import (
    DanmakuMessage,
    LivestreamEvent,
    LivestreamEventType,
    TopicSeed,
)
from animetta.services.bilibili.livestream_session import StaleGenerationError
from animetta.services.bilibili.reply_media import (
    BroadcastMediaTurn,
    acquire_reply_media_turn,
    finish_reply_media_turn,
)
from animetta.services.livestream_narration import NarrationCue
from animetta.services.scene_analysis.models import SceneGuidance


class FakeGateway:
    def __init__(self, room_id: int, _sessdata: str) -> None:
        self.room_id = room_id
        self.on_message = None
        self.on_status = None
        self.stopped = False

    def set_message_callback(self, callback) -> None:
        self.on_message = callback

    def set_status_callback(self, callback) -> None:
        self.on_status = callback

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True


async def settle_callbacks() -> None:
    for _ in range(4):
        await asyncio.sleep(0)


def _snapshot(state: str = "stopped") -> dict[str, object]:
    connected = state in {"prelive", "live"}
    return {
        "state": state,
        "connected": connected,
        "room_id": 123 if connected else None,
        "desired_room_id": 123 if state != "stopped" else None,
        "retry_count": 0,
        "error_code": None,
        "generation_id": 1 if state != "stopped" else 0,
        "message": state.title(),
        "updated_at": 100.0,
    }


@pytest.fixture
def handler_harness():
    sio = MagicMock()
    sio.emit = AsyncMock()
    session = MagicMock()
    session.snapshot.return_value = _snapshot()
    session.set_room = AsyncMock(return_value=_snapshot("connecting"))
    session.stop = AsyncMock(return_value=_snapshot())
    handler = BilibiliHandlers(
        sio=sio,
        session_manager=MagicMock(),
        admin=MagicMock(),
        session=session,
        sessdata="server-secret",
    )
    return handler, sio, session


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, {}, {"room_id": 0}, {"room_id": "123"}])
async def test_connect_rejects_invalid_commands(handler_harness, data) -> None:
    handler, _, session = handler_harness

    ack = await handler.on_bilibili_connect("sid-1", data)

    assert ack == {
        "accepted": False,
        "state": "stopped",
        "error_code": "invalid_room_id",
        "message": "Invalid room ID",
    }
    session.set_room.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_acknowledges_acceptance_not_connection_truth(
    handler_harness,
) -> None:
    handler, sio, session = handler_harness

    ack = await handler.on_bilibili_connect("sid-1", {"room_id": 123})

    session.set_room.assert_awaited_once_with(
        123,
        sessdata="server-secret",
        expected_generation_id=None,
    )
    assert ack == {
        "accepted": True,
        "state": "connecting",
        "error_code": None,
        "message": "Command accepted",
    }
    sio.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnect_accepts_missing_payload(handler_harness) -> None:
    handler, _, session = handler_harness

    ack = await handler.on_bilibili_disconnect("sid-1")

    session.stop.assert_awaited_once()
    assert ack["accepted"] is True
    assert ack["state"] == "stopped"


@pytest.mark.asyncio
async def test_update_room_uses_same_atomic_session_command(handler_harness) -> None:
    handler, _, session = handler_harness

    ack = await handler.on_bilibili_update_room("sid-1", {"room_id": 123})

    session.set_room.assert_awaited_once_with(
        123,
        sessdata="server-secret",
        expected_generation_id=None,
    )
    assert ack["state"] == "connecting"


@pytest.mark.asyncio
async def test_generation_guard_is_forwarded_to_atomic_room_command(handler_harness) -> None:
    handler, _, session = handler_harness

    await handler.on_bilibili_update_room(
        "sid-1",
        {"room_id": 456, "expected_generation_id": 1},
    )

    session.set_room.assert_awaited_once_with(
        456,
        sessdata="server-secret",
        expected_generation_id=1,
    )


@pytest.mark.asyncio
async def test_stale_generation_returns_conflict_without_overwriting_session(
    handler_harness,
) -> None:
    handler, _, session = handler_harness
    session.set_room.side_effect = StaleGenerationError("changed")

    ack = await handler.on_bilibili_connect(
        "sid-1",
        {"room_id": 456, "expected_generation_id": 0},
    )

    assert ack == {
        "accepted": False,
        "state": "stopped",
        "error_code": "stale_generation",
        "message": "Session generation changed",
    }


@pytest.mark.asyncio
async def test_disconnect_rejects_invalid_generation_without_stopping(handler_harness) -> None:
    handler, _, session = handler_harness

    ack = await handler.on_bilibili_disconnect(
        "sid-1",
        {"expected_generation_id": True},
    )

    assert ack["error_code"] == "invalid_generation_id"
    session.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnect_forwards_generation_guard(handler_harness) -> None:
    handler, _, session = handler_harness

    ack = await handler.on_bilibili_disconnect(
        "sid-1",
        {"expected_generation_id": 1},
    )

    session.stop.assert_awaited_once_with(expected_generation_id=1)
    assert ack["accepted"] is True


@pytest.mark.asyncio
async def test_new_client_receives_current_truthful_snapshot(handler_harness) -> None:
    handler, sio, session = handler_harness
    session.snapshot.return_value = _snapshot("reconnecting")

    await handler.emit_current_snapshot("sid-new")

    sio.emit.assert_awaited_once_with(
        "bilibili:danmaku_status",
        _snapshot("reconnecting"),
        to="sid-new",
    )


@pytest.mark.asyncio
async def test_session_status_sink_broadcasts_full_snapshot(handler_harness) -> None:
    handler, sio, _ = handler_harness
    payload = _snapshot("live")

    await handler.emit_status_snapshot(payload)

    sio.emit.assert_awaited_once_with("bilibili:danmaku_status", payload)


@pytest.mark.asyncio
async def test_session_generation_change_cancels_minecraft_narration(handler_harness) -> None:
    handler, _, _ = handler_harness
    switch_generation = AsyncMock()
    handler.bind_narration_generation_switch(switch_generation)
    first = _snapshot("live")
    first["generation_id"] = 4
    second = {**first, "generation_id": 5}

    await handler.emit_status_snapshot(first)
    await handler.emit_status_snapshot(first)
    await handler.emit_status_snapshot(second)

    switch_generation.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_minecraft_narration_owns_a_tool_memory_and_checkpoint_free_graph(
    handler_harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler, sio, _ = handler_harness
    context = MagicMock()
    dedicated = MagicMock()
    dedicated.stop = AsyncMock()
    create = AsyncMock(return_value=dedicated)
    handler.admin.get_or_create_context = AsyncMock(return_value=context)
    monkeypatch.setattr(LangGraphOrchestrator, "create", create)

    first = await handler._get_or_create_minecraft_narration_orchestrator()
    second = await handler._get_or_create_minecraft_narration_orchestrator()

    assert first is second is dedicated
    handler.admin.get_or_create_context.assert_awaited_once_with("minecraft:narration")
    create.assert_awaited_once_with(
        session_id="minecraft:narration",
        service_context=context,
        socketio=sio,
        emotion_analyzer=context.emotion_analyzer,
        enable_tools=False,
        enable_memory=False,
        tools_config={},
        checkpoint_runtime=None,
        force_standard_graph=True,
    )

    await handler.close_minecraft_narration()
    dedicated.stop.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_viewer_media_can_start_while_minecraft_composer_is_pending(
    handler_harness,
) -> None:
    handler, _, _ = handler_harness
    composer_started = asyncio.Event()
    release_composer = asyncio.Event()
    narration_started = AsyncMock()

    class SlowNarrationOrchestrator:
        async def process_text(self, **_kwargs):
            composer_started.set()
            await release_composer.wait()
            await acquire_reply_media_turn()
            await finish_reply_media_turn()
            return {"response_text": "目标已经确认完成。"}

    handler._minecraft_narration_orchestrator = SlowNarrationOrchestrator()
    cue = NarrationCue(
        cue_id="cue-1",
        source_event_id="activity:1",
        phase="finished",
        visual_text="目标已经确认完成。",
        emotion="relieved",
        priority=40,
        expires_at=time.monotonic() + 60,
    )
    narration = asyncio.create_task(handler.process_minecraft_narration(cue, narration_started))
    await composer_started.wait()

    viewer = BroadcastMediaTurn(handler.media_arbiter, priority=20)
    await asyncio.wait_for(viewer.acquire(), timeout=0.1)
    release_composer.set()
    await asyncio.sleep(0)
    narration_started.assert_not_awaited()

    await viewer.finish()
    assert await narration == "目标已经确认完成。"
    narration_started.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_live_event_broadcast_includes_room_and_generation(handler_harness) -> None:
    handler, sio, _ = handler_harness
    event = LivestreamEvent(
        sequence=7,
        offset_ms=1250,
        event_type=LivestreamEventType.GIFT,
        actor_id="viewer-42",
        text="送出礼物",
        payload={"user_id": 42, "gift_name": "花"},
    )

    await handler._broadcast_live_event(event, room_id=123, generation_id=4)

    sio.emit.assert_awaited_once_with(
        "bilibili:live_event",
        {
            "room_id": 123,
            "generation_id": 4,
            "sequence": 7,
            "offset_ms": 1250,
            "event_type": "gift",
            "actor_id": "viewer-42",
            "text": "送出礼物",
            "payload": {"user_id": 42, "gift_name": "花"},
        },
    )


@pytest.mark.asyncio
async def test_real_session_integration_hot_switches_and_rejects_stale_raw() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    gateways: list[FakeGateway] = []

    def factory(room_id: int, sessdata: str) -> FakeGateway:
        gateway = FakeGateway(room_id, sessdata)
        gateways.append(gateway)
        return gateway

    handler = BilibiliHandlers(
        sio,
        MagicMock(),
        MagicMock(),
        gateway_factory=factory,
    )
    handler.configure({"reply_policy": {"enabled": False}})

    first_ack = await handler.on_bilibili_connect("sid", {"room_id": 100})
    stale_gateway = gateways[0]
    assert first_ack["state"] == "connecting"
    stale_gateway.on_message(DanmakuMessage(text="first"))
    await settle_callbacks()

    switch_ack = await handler.on_bilibili_update_room("sid", {"room_id": 200})
    stale_gateway.on_message(DanmakuMessage(text="stale"))
    gateways[1].on_message(DanmakuMessage(text="current"))
    await settle_callbacks()

    raw_texts = [
        call.args[1]["text"]
        for call in sio.emit.await_args_list
        if call.args[0] == "bilibili:danmaku"
    ]
    assert switch_ack["state"] == "connecting"
    assert stale_gateway.stopped is True
    assert raw_texts == ["first", "current"]


@pytest.mark.asyncio
async def test_real_session_integration_serializes_admitted_ai_reply() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    gateway = FakeGateway(300, "")
    handler = BilibiliHandlers(
        sio,
        MagicMock(),
        MagicMock(),
        reply_policy=ReplyPolicyConfig(
            ordinary_sample_rate=1.0,
            per_user_cooldown_seconds=0,
            duplicate_window_seconds=0,
        ),
        gateway_factory=lambda _room_id, _sessdata: gateway,
    )
    handler._process_ai_reply = AsyncMock()
    await handler.on_bilibili_connect("sid", {"room_id": 300})
    message = DanmakuMessage(text="普通弹幕", timestamp=time.time())

    gateway.on_message(message)
    for _ in range(20):
        await settle_callbacks()
        if handler._process_ai_reply.await_count:
            break

    handler._process_ai_reply.assert_awaited_once()
    assert handler._process_ai_reply.await_args.args == (message, 300)
    assert isinstance(handler._process_ai_reply.await_args.kwargs["reply_id"], str)
    assert handler.metrics.displayed == 1
    assert handler.metrics.admitted == 1
    await handler.stop_bilibili()


class ActiveSceneRuntime:
    def __init__(self, guidance: SceneGuidance) -> None:
        self.guidance = guidance
        self.bound_llm = None
        self.host_replies: list[str] = []

    def bind_gateway(self, gateway) -> None:
        self.bound_llm = gateway

    async def guidance_for_reply(self) -> SceneGuidance:
        return self.guidance

    async def record_host_reply(self, text: str) -> None:
        self.host_replies.append(text)


async def test_room_start_binds_profile_llm_before_any_reply() -> None:
    guidance = SceneGuidance(
        scene_revision=0,
        scene_summary="Livestream is starting.",
        response_objective="Welcome the room.",
        confidence=0,
        expires_at=time.time() + 60,
    )
    scene_runtime = ActiveSceneRuntime(guidance)
    llm = MagicMock()
    service_context = MagicMock()
    service_context.llm_engine = llm
    admin = MagicMock()
    admin.get_or_create_context = AsyncMock(return_value=service_context)
    session = MagicMock()
    session.set_room = AsyncMock(return_value=_snapshot("connecting"))
    handler = BilibiliHandlers(
        MagicMock(),
        MagicMock(),
        admin,
        session=session,
        scene_runtime=scene_runtime,
    )

    await handler.start_bilibili(123)

    admin.get_or_create_context.assert_awaited_once_with("bilibili")
    assert scene_runtime.bound_llm is not None
    assert scene_runtime.bound_llm._llm is llm
    session.set_room.assert_awaited_once_with(
        123,
        sessdata="",
        expected_generation_id=None,
    )


async def test_active_scene_guidance_enters_turn_metadata_and_host_reply_feeds_back() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    guidance = SceneGuidance(
        scene_revision=2,
        scene_summary="A room joke is rising.",
        response_objective="Build on the joke without changing topics.",
        tone=["playful"],
        confidence=0.9,
        expires_at=time.time() + 60,
    )
    scene_runtime = ActiveSceneRuntime(guidance)
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(
        return_value={"response_text": "接住了，这波是穿模艺术。"}
    )
    orchestrator.service_context = MagicMock()
    orchestrator.service_context.llm_engine = MagicMock()
    admin = MagicMock()
    admin._get_or_create_orchestrator = AsyncMock(return_value=orchestrator)
    handler = BilibiliHandlers(
        sio,
        MagicMock(),
        admin,
        session=MagicMock(),
        scene_runtime=scene_runtime,
    )

    await handler._process_ai_reply(
        DanmakuMessage(text="穿模了", user_name="观众", user_id=7),
        321,
    )

    kwargs = orchestrator.process_text.await_args.kwargs
    assert SceneGuidance.model_validate(kwargs["scene_guidance"]) == guidance
    assert kwargs["source_message_id"]
    assert kwargs["reply_id"] == kwargs["task_id"]
    assert kwargs["received_at"] > 0
    assert not [call for call in sio.emit.await_args_list if call.args[0].startswith("chat:")]
    assert scene_runtime.host_replies == ["接住了，这波是穿模艺术。"]


async def test_proactive_topic_uses_trusted_host_identity_without_fake_danmaku() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    session = MagicMock()
    session.snapshot.return_value = _snapshot("live")
    scene_runtime = ActiveSceneRuntime(
        SceneGuidance(
            scene_revision=2,
            scene_summary="A room joke is rising.",
            response_objective="Stay on topic.",
            confidence=0.9,
            expires_at=time.time() + 60,
        )
    )
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(
        return_value={"response_text": "企鹅不会飞，因为没有买机票。"}
    )
    admin = MagicMock()
    admin.live_session_id = "live-session-1"
    admin._get_or_create_orchestrator = AsyncMock(return_value=orchestrator)
    handler = BilibiliHandlers(
        sio,
        MagicMock(),
        admin,
        session=session,
        scene_runtime=scene_runtime,
    )
    task_id = str(uuid4())

    response = await handler._process_proactive_topic(
        TopicSeed(
            kind="scene",
            subject="企鹅",
            dedupe_key="scene:企鹅:2",
            provenance="scene_runtime",
        ),
        task_id,
        123,
        1,
        ("鲨鱼生活在海里，因为陆地很难游泳。",),
    )

    kwargs = orchestrator.process_text.await_args.kwargs
    assert response == "企鹅不会飞，因为没有买机票。"
    assert kwargs["source"] == "bilibili:proactive_topic"
    assert kwargs["actor_role"] == "host"
    assert kwargs["audience"] == "livestream"
    assert kwargs["task_id"] == kwargs["turn_id"] == task_id
    assert kwargs["proactive_topic_max_chars"] == 36
    assert kwargs["proactive_recent_outputs"] == ["鲨鱼生活在海里，因为陆地很难游泳。"]
    assert scene_runtime.host_replies == ["企鹅不会飞，因为没有买机票。"]
    assert not [call for call in sio.emit.await_args_list if call.args[0] == "danmaku_ai_reply"]


async def test_proactive_audio_stop_is_correlated_to_the_owned_task(handler_harness) -> None:
    handler, sio, _ = handler_harness
    task_id = str(uuid4())

    await handler._interrupt_proactive_audio(task_id)

    sio.emit.assert_awaited_once()
    event, payload = sio.emit.await_args.args[:2]
    assert event == "chat:stop_audio"
    assert payload == {
        "message_id": task_id,
        "conversation_id": task_id,
        "task_id": task_id,
        "turn_id": task_id,
    }


async def test_program_danmaku_uses_controlled_actor_probe_and_checkpoint_metadata() -> None:
    sio = MagicMock()
    sio.emit = AsyncMock()
    scene_runtime = ActiveSceneRuntime(
        SceneGuidance(
            scene_revision=1,
            scene_summary="ambient",
            response_objective="ambient",
            confidence=1,
            expires_at=time.time() + 60,
        )
    )
    orchestrator = MagicMock()
    orchestrator.process_text = AsyncMock(return_value={"response_text": "记得，小岚。"})
    admin = MagicMock()
    admin._get_or_create_orchestrator = AsyncMock(return_value=orchestrator)
    handler = BilibiliHandlers(
        sio,
        MagicMock(),
        admin,
        session=MagicMock(),
        scene_runtime=scene_runtime,
    )
    scripted_guidance = SceneGuidance(
        scene_revision=9,
        scene_summary="Q9",
        response_objective="回答称呼",
        confidence=1,
        expires_at=time.time() + 60,
    ).model_dump(mode="json")

    result = await handler.process_program_danmaku(
        "我回来啦，还记得我是谁吗？",
        {
            "actor_id": "program:run-1",
            "display_name": "首播测试观众",
            "turn_id": "00000000-0000-4000-8000-000000000009",
            "program_run_id": "run-1",
            "program_beat_id": "q09",
            "is_probe": True,
            "memory_mode": "probe",
            "checkpoint_request": CheckpointRequest(
                thread_id="program:run-1:q09",
                owner_kind="program",
                owner_id="run-1",
                retention="temporary",
            ),
            "scene_guidance": scripted_guidance,
        },
        room_id=1,
    )

    kwargs = orchestrator.process_text.await_args.kwargs
    assert result["response_text"] == "记得，小岚。"
    assert kwargs["user_id"] == "program:run-1"
    assert kwargs["turn_id"] == "00000000-0000-4000-8000-000000000009"
    assert kwargs["is_probe"] is True
    assert kwargs["memory_mode"] == "probe"
    assert kwargs["checkpoint_request"] == CheckpointRequest(
        thread_id="program:run-1:q09",
        owner_kind="program",
        owner_id="run-1",
        retention="temporary",
    )
    assert kwargs["scene_guidance"] == scripted_guidance
    assert scene_runtime.host_replies == []
