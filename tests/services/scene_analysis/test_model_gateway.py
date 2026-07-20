from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from animetta.services.llm.interface import LLMInterface
from animetta.services.scene_analysis.models import (
    LiveSceneState,
    NormalizedSceneEvent,
    SceneEvidence,
    SceneMetrics,
)


def _gateway_module():
    try:
        spec = importlib.util.find_spec("animetta.services.scene_analysis.model_gateway")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "scene model gateway must exist"
    return importlib.import_module("animetta.services.scene_analysis.model_gateway")


class _BaseFakeLLM(LLMInterface):
    def __init__(self) -> None:
        self.history: list[dict[str, str]] = [{"role": "user", "content": "main history"}]
        self.chat_calls = 0

    async def chat(self, user_input: str, **kwargs: Any) -> str:
        self.chat_calls += 1
        self.history.append({"role": "user", "content": user_input})
        return "unsafe"

    async def chat_stream(self, user_input: str, **kwargs: Any) -> AsyncIterator[str]:
        del user_input, kwargs
        if False:
            yield ""

    def set_system_prompt(self, prompt: str) -> None:
        del prompt

    def get_history(self) -> list[dict[str, Any]]:
        return list(self.history)

    def clear_history(self) -> None:
        self.history.clear()

    async def close(self) -> None:
        return None

    def handle_interrupt(self, heard_response: str = "") -> None:
        del heard_response

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        del conf_uid, history_uid


class NativeSceneLLM(_BaseFakeLLM):
    def __init__(self, responses: list[str], delay: float = 0) -> None:
        super().__init__()
        self.responses = responses
        self.delay = delay
        self.message_calls: list[tuple[list[dict], dict[str, Any]]] = []

    async def chat_messages(self, messages: list[dict], **kwargs: Any) -> str:
        self.message_calls.append((messages, kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.responses.pop(0)


class UnsafeSceneLLM(_BaseFakeLLM):
    pass


def _state_and_evidence() -> tuple[LiveSceneState, SceneEvidence]:
    state = LiveSceneState.initial(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        now=100.0,
    )
    event = NormalizedSceneEvent(
        event_id="evt-1",
        event_seq=1,
        session_id="live-1",
        room_id=42,
        generation_id=1,
        occurred_at=101.0,
        event_type="danmaku",
        actor_id="viewer-1",
        text="哈哈穿模了",
    )
    evidence = SceneEvidence(
        session_id="live-1",
        room_id=42,
        generation_id=1,
        from_event_seq=1,
        to_event_seq=1,
        duration_seconds=1,
        metrics=SceneMetrics(event_count=1, danmaku_per_minute=60, unique_users=1),
        representative_events=[event],
    )
    return state, evidence


async def test_native_scene_call_is_structured_and_history_neutral() -> None:
    module = _gateway_module()
    state, evidence = _state_and_evidence()
    response = json.dumps(
        {
            "base_revision": 0,
            "consumed_event_seq": 1,
            "scene_stage": "topic_rising",
            "pace": "fast",
            "scene_summary": "A clipping joke is rising.",
            "confidence": 0.8,
            "generated_at": 102.0,
        }
    )
    llm = NativeSceneLLM([response])
    original_history = llm.get_history()

    patch = await module.SceneModelGateway(llm).reflect(evidence, state)

    assert patch.base_revision == 0
    assert patch.consumed_event_seq == 1
    assert llm.get_history() == original_history
    assert llm.chat_calls == 0
    _, kwargs = llm.message_calls[0]
    assert kwargs["temperature"] == 0
    assert kwargs["max_tokens"] == 800
    assert kwargs["response_format"] == {"type": "json_object"}


async def test_unsupported_provider_never_falls_back_to_chat() -> None:
    module = _gateway_module()
    state, evidence = _state_and_evidence()
    llm = UnsafeSceneLLM()

    with pytest.raises(module.SceneModelGatewayError) as exc_info:
        await module.SceneModelGateway(llm).reflect(evidence, state)

    assert exc_info.value.code == "history_unsafe"
    assert llm.chat_calls == 0
    assert llm.get_history() == [{"role": "user", "content": "main history"}]


async def test_scene_call_timeout_is_typed() -> None:
    module = _gateway_module()
    state, evidence = _state_and_evidence()
    llm = NativeSceneLLM(["{}"], delay=0.05)

    with pytest.raises(module.SceneModelGatewayError) as exc_info:
        await module.SceneModelGateway(llm, timeout_seconds=0.01).reflect(evidence, state)

    assert exc_info.value.code == "timeout"


async def test_invalid_json_fails_without_exceeding_one_provider_call() -> None:
    module = _gateway_module()
    state, evidence = _state_and_evidence()
    llm = NativeSceneLLM(["not-json"])

    with pytest.raises(module.SceneModelGatewayError) as exc_info:
        await module.SceneModelGateway(llm).reflect(evidence, state)

    assert exc_info.value.code == "invalid_json"
    assert len(llm.message_calls) == 1


async def test_schema_error_fails_without_exceeding_one_provider_call() -> None:
    module = _gateway_module()
    state, evidence = _state_and_evidence()
    llm = NativeSceneLLM(["{}"])

    with pytest.raises(module.SceneModelGatewayError) as exc_info:
        await module.SceneModelGateway(llm).reflect(evidence, state)

    assert exc_info.value.code == "schema_invalid"
    assert str(exc_info.value) == "schema_invalid"
    assert len(llm.message_calls) == 1
