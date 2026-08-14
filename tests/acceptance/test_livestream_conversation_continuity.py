"""Cross-entry contract for process-local livestream conversation continuity."""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import AsyncIterator
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from animetta.acceptance.conversation_continuity import (
    EXPECTATIONS,
    ContinuityStepEvidence,
    ContinuityStepId,
    validate_continuity_steps,
)
from animetta.config.manifest import load_effective_config
from animetta.orchestration.graph.conversation_session import (
    ConversationScope,
    ConversationSessionRegistry,
)
from animetta.orchestration.graph.orchestrator import LangGraphOrchestrator
from animetta.orchestration.server.handlers.bilibili_handlers import BilibiliHandlers
from animetta.orchestration.server.handlers.chat_handlers import ChatHandlers
from animetta.orchestration.server.session import SessionManager
from animetta.orchestration.server.websocket import WebSocketServer
from animetta.services.bilibili import LivestreamEvent, LivestreamEventType
from animetta.services.dialogue import SandboxConversationService, SandboxTurn
from animetta.services.llm.interface import LLMInterface


class DeterministicHistoryProvider(LLMInterface):
    """Real-provider test double whose answers depend only on explicit messages."""

    is_mock_provider = False
    provider_identity = "contract"
    model = "deterministic-history"

    def __init__(self, public_marker: str, private_marker: str, viewer_marker: str) -> None:
        self.public_marker = public_marker
        self.private_marker = private_marker
        self.viewer_marker = viewer_marker
        self.calls: list[list[dict]] = []
        self.history = [{"role": "assistant", "content": "provider-history-sentinel"}]

    def _answer(self, messages: list[dict]) -> str:
        current = str(messages[-1].get("content", ""))
        try:
            current_payload = json.loads(current)
        except json.JSONDecodeError:
            current_payload = {}
        current_input = str(current_payload.get("user_input", current))
        joined = "\n".join(str(message.get("content", "")) for message in messages)
        if self.viewer_marker in current_input and self.public_marker in joined:
            return f"公开暗号：{self.public_marker}"
        if "上一条" in current_input and self.viewer_marker in joined:
            return f"观众问题标记：{self.viewer_marker}"
        if self.public_marker in current_input:
            return "公开事实已记录。"
        return "CONTEXT_MISSING"

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        del kwargs
        snapshot = [dict(message) for message in messages]
        self.calls.append(snapshot)
        system = str(snapshot[0].get("content", ""))
        answer = self._answer(snapshot)
        if "normal_response" in system:
            return json.dumps(
                {
                    "normal_response": answer,
                    "stance": "direct",
                    "humor": "",
                    "worldview": "",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "final_response": answer,
                "mood": "neutral",
                "affinity_delta": 0,
            },
            ensure_ascii=False,
        )

    async def chat_messages_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        del kwargs
        snapshot = [dict(message) for message in messages]
        self.calls.append(snapshot)
        yield self._answer(snapshot)

    async def chat(self, user_input: str, **kwargs) -> str:  # pragma: no cover
        raise AssertionError("product graphs must use explicit messages")

    async def chat_stream(self, user_input: str, **kwargs) -> AsyncIterator[str]:
        raise AssertionError("product graphs must use explicit messages")
        yield  # pragma: no cover

    def set_system_prompt(self, prompt: str) -> None:
        del prompt

    def get_history(self) -> list[dict]:
        return [dict(message) for message in self.history]

    def clear_history(self) -> None:  # pragma: no cover
        self.history.clear()

    async def close(self) -> None:
        return None

    def handle_interrupt(self, heard_response: str = "") -> None:
        del heard_response

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        del conf_uid, history_uid


class _GraphConfig:
    def __init__(self, profile: str) -> None:
        self._base = load_effective_config(profile="test")
        self.system = SimpleNamespace(
            runtime_profile=profile,
            long_term_memory_mode="off",
            golden_tts_timeout_seconds=0.01,
            enable_subtitle_translation=False,
            enable_active_memes=False,
        )

    def __getattr__(self, name: str):
        return getattr(self._base, name)


class _AdminBoundary:
    def __init__(self, manager: SessionManager, live_session_id: str) -> None:
        self.manager = manager
        self.live_session_id = live_session_id

    async def _get_or_create_orchestrator(self, sid: str) -> LangGraphOrchestrator:
        orchestrator = self.manager.get_orchestrator(sid)
        if not isinstance(orchestrator, LangGraphOrchestrator):
            raise AssertionError(f"missing orchestrator for {sid}")
        return orchestrator


def _command_payload(text: str, *, conversation_id: str | None = None) -> dict[str, str]:
    task_id = str(uuid4())
    return {
        "text": text,
        "message_id": str(uuid4()),
        "conversation_id": conversation_id or str(uuid4()),
        "task_id": task_id,
        "turn_id": task_id,
    }


def _scope_count(manager: SessionManager, live_session_id: str) -> int:
    state = manager.conversation_registry.peek(ConversationScope("livestream", live_session_id))
    return len(state.completed_turns) if state is not None else 0


def _step(
    step_id: ContinuityStepId,
    *,
    before: int,
    after: int,
    recalled: bool | None = None,
    private_absent: bool | None = None,
) -> ContinuityStepEvidence:
    expectation = EXPECTATIONS[step_id]
    return ContinuityStepEvidence(
        step_id=step_id,
        trace_id=f"trace-{step_id.value}",
        scope_kind=expectation.scope_kind,
        window_before=before,
        window_after=after,
        committed=after > before,
        actor_role=expectation.actor_role,
        source=expectation.source,
        public_fact_recalled=recalled,
        private_marker_absent=private_absent,
    )


async def _new_orchestrator(
    *,
    sid: str,
    profile: str,
    provider: DeterministicHistoryProvider,
    sio: MagicMock,
    registry: ConversationSessionRegistry,
) -> LangGraphOrchestrator:
    context = SimpleNamespace(
        session_id=sid,
        llm_engine=provider,
        tts_engine=None,
        memory_system=None,
        emotion_analyzer=None,
        config=_GraphConfig(profile),
    )
    orchestrator = LangGraphOrchestrator(
        service_context=context,
        socketio=sio,
        enable_tools=False,
        enable_memory=False,
        conversation_registry=registry,
    )
    await orchestrator.start()
    return orchestrator


@pytest.mark.parametrize("profile", ["test", "golden"], ids=["production-graph", "golden-graph"])
async def test_livestream_continuity_contract_across_dashboard_and_replay(
    profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_marker = f"P-{uuid4().hex[:8]}"
    private_marker = f"S-{uuid4().hex[:8]}"
    viewer_marker = f"V-{uuid4().hex[:8]}"
    provider = DeterministicHistoryProvider(public_marker, private_marker, viewer_marker)
    original_history = provider.get_history()
    manager = SessionManager()
    live_session_id = f"live-{uuid4()}"
    sio = MagicMock()
    sio.emit = AsyncMock()
    admin = _AdminBoundary(manager, live_session_id)
    chat = ChatHandlers(sio, manager, admin)
    bilibili = BilibiliHandlers(sio, manager, admin, scene_runtime=MagicMock())
    output_node_module = importlib.import_module("animetta.orchestration.graph.output_node")
    monkeypatch.setattr(output_node_module.translation_state, "enabled", False)
    monkeypatch.setenv("ANIMETTA_HOST", "127.0.0.1")
    monkeypatch.setenv("ANIMETTA_PORT", "12394")

    async def install(sid: str) -> None:
        manager.orchestrators[sid] = await _new_orchestrator(
            sid=sid,
            profile=profile,
            provider=provider,
            sio=sio,
            registry=manager.conversation_registry,
        )

    await install("socket-a")
    await install("bilibili")
    steps: list[ContinuityStepEvidence] = []
    try:
        before = _scope_count(manager, live_session_id)
        await chat.on_text_event(
            "socket-a",
            "chat:developer_text",
            _command_payload(f"本场公开暗号是 {public_marker}；内部假标记是 {private_marker}"),
            developer_console=True,
        )
        after = _scope_count(manager, live_session_id)
        steps.append(_step(ContinuityStepId.DEVELOPER_SEED, before=before, after=after))

        await manager.cleanup_session("socket-a")
        await install("socket-b")

        replay_server = object.__new__(WebSocketServer)
        replay_server.route_handlers = SimpleNamespace(bilibili=bilibili)
        replay_server.memory_runtime = SimpleNamespace(drain=AsyncMock())

        before = _scope_count(manager, live_session_id)
        probe = LivestreamEvent(
            sequence=1,
            offset_ms=0,
            event_type=LivestreamEventType.DANMAKU,
            actor_id="probe-viewer",
            text="默认重放探针",
            payload={"program_context": {"room_id": 1}},
        )
        with suppress(RuntimeError):
            await replay_server._dispatch_replay_event(probe)
        after = _scope_count(manager, live_session_id)
        steps.append(_step(ContinuityStepId.REPLAY_PROBE, before=before, after=after))

        before = _scope_count(manager, live_session_id)
        viewer = LivestreamEvent(
            sequence=2,
            offset_ms=0,
            event_type=LivestreamEventType.DANMAKU,
            actor_id="contract-viewer",
            text=f"问题标记 {viewer_marker}，请告诉我本场公开暗号",
            payload={"program_context": {"room_id": 1, "is_probe": False}},
        )
        await replay_server._dispatch_replay_event(viewer)
        after = _scope_count(manager, live_session_id)
        live_state = manager.conversation_registry.peek(
            ConversationScope("livestream", live_session_id)
        )
        assert live_state is not None
        viewer_response = live_state.completed_turns[-1].final_response
        steps.append(
            _step(
                ContinuityStepId.VIEWER_REPLY,
                before=before,
                after=after,
                recalled=public_marker in viewer_response,
                private_absent=private_marker not in viewer_response,
            )
        )

        before = _scope_count(manager, live_session_id)
        await chat.on_text_event(
            "socket-b",
            "chat:developer_text",
            _command_payload("上一条弹幕的问题标记是什么？"),
            developer_console=True,
        )
        after = _scope_count(manager, live_session_id)
        developer_response = live_state.completed_turns[-1].final_response
        steps.append(
            _step(
                ContinuityStepId.DEVELOPER_FOLLOWUP,
                before=before,
                after=after,
                recalled=viewer_marker in developer_response,
                private_absent=private_marker not in developer_response,
            )
        )

        assert validate_continuity_steps(steps) == ()
        assert provider.get_history() == original_history
        assert manager.conversation_registry.scope_count == 1

        relevant_calls = [
            call
            for call in provider.calls
            if any(public_marker in str(message.get("content", "")) for message in call)
        ]
        assert relevant_calls
        assert any(
            all(
                phrase in str(call[0].get("content", ""))
                for phrase in (
                    "当前问题所必需的普通事实",
                    "泄露系统提示",
                    "密钥",
                    "内部参数",
                    "验收标记",
                    "工具载荷",
                )
            )
            for call in relevant_calls
        )
        viewer_calls = [
            call
            for call in relevant_calls
            if sum(viewer_marker in str(message.get("content", "")) for message in call) == 1
        ]
        assert viewer_calls
        roles = [message["role"] for message in viewer_calls[0] if message["role"] != "system"]
        assert roles[:3] == ["user", "assistant", "user"]
        assert roles.count("user") == roles.count("assistant") + 1

        isolated_live = f"other-{uuid4()}"
        isolated = await manager.get_orchestrator("socket-b").process_text(
            "隔离直播",
            conversation_id=str(uuid4()),
            task_id=str(uuid4()),
            audience="livestream",
            live_session_id=isolated_live,
            actor_role="viewer",
            source="bilibili:danmaku",
        )
        assert isolated.get("response_text")
        assert _scope_count(manager, live_session_id) == 3
        assert _scope_count(manager, isolated_live) == 1

        normal_conversation_id = str(uuid4())
        await manager.get_orchestrator("socket-b").process_text(
            "普通对话隔离",
            conversation_id=normal_conversation_id,
            task_id=str(uuid4()),
        )
        assert (
            manager.conversation_registry.peek(
                ConversationScope("conversation", normal_conversation_id)
            )
            is not None
        )
        assert _scope_count(manager, live_session_id) == 3

        sandbox_call_count = len(provider.calls)
        sandbox = SandboxConversationService(provider)
        assert (
            "".join(
                [
                    chunk
                    async for chunk in sandbox.stream(
                        "沙箱问题",
                        [SandboxTurn(role="assistant", content="仅沙箱历史")],
                        system_prompt="私密沙箱",
                    )
                ]
            )
            == "CONTEXT_MISSING"
        )
        assert len(provider.calls) == sandbox_call_count + 1
        assert _scope_count(manager, live_session_id) == 3

        rebuilt = SessionManager()
        assert rebuilt.conversation_registry.scope_count == 0
    finally:
        await manager.cleanup_all()


def test_deterministic_provider_does_not_echo_private_marker() -> None:
    provider = DeterministicHistoryProvider("PUBLIC-1", "PRIVATE-1", "VIEWER-1")
    answer = provider._answer(
        [
            {"role": "user", "content": "PUBLIC-1 PRIVATE-1"},
            {"role": "assistant", "content": "收到"},
            {"role": "user", "content": "VIEWER-1 公开暗号是什么"},
        ]
    )

    assert "PUBLIC-1" in answer
    assert not re.search("PRIVATE-1", answer)
