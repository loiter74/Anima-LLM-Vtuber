from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from animetta.orchestration.graph.conversation_session import ConversationSessionState
from animetta.orchestration.graph.dialogue_nodes import (
    anima_composer_node,
    conversation_finalizer_node,
    reasoner_node,
    response_guard_node,
)
from animetta.orchestration.graph.state import create_initial_state
from animetta.services.llm.interface import LLMInterface


class SequencedLLM(LLMInterface):
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[dict]] = []
        self.history: list[dict] = []

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        self.calls.append(messages)
        response = self.responses.pop(0)
        if response == "RAISE":
            raise RuntimeError("provider failure")
        return response

    async def chat(self, user_input: str, **kwargs) -> str:
        raise AssertionError

    async def chat_stream(self, user_input: str, **kwargs) -> AsyncIterator[str]:
        if False:
            yield ""

    def set_system_prompt(self, prompt: str) -> None:
        pass

    def get_history(self) -> list[dict]:
        return list(self.history)

    def clear_history(self) -> None:
        self.history.clear()

    async def close(self) -> None:
        pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        pass

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass


class SharedSessionLLM(SequencedLLM):
    def __init__(self) -> None:
        super().__init__([])
        self.history = [{"role": "assistant", "content": "shared-provider-history"}]

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        self.calls.append(messages)
        system = messages[0]["content"]
        current = messages[-1]["content"]
        await asyncio.sleep(0)
        if "normal_response" in system:
            return json.dumps(
                {
                    "normal_response": f"reasoned:{current}",
                    "stance": "direct",
                    "humor": "",
                    "worldview": "",
                }
            )
        payload = json.loads(current)
        return json.dumps(
            {
                "final_response": f"final:{payload['user_input']}",
                "mood": "neutral",
                "affinity_delta": 0,
            }
        )


def config(llm: LLMInterface) -> dict:
    return {
        "configurable": {
            "service_context": SimpleNamespace(llm_engine=llm),
            "conversation_session": ConversationSessionState(),
        }
    }


def state():
    result = create_initial_state("session", user_text="你好")
    result["system_prompt"] = "你是 Anima。"
    return result


@pytest.mark.asyncio
async def test_normal_turn_calls_reasoner_then_composer_exactly_once() -> None:
    llm = SequencedLLM(
        [
            '{"normal_response":"你好","stance":"友好","humor":"","worldview":""}',
            '{"final_response":"旅人，你好呀。","mood":"bright","affinity_delta":1}',
        ]
    )
    current = state()
    current.update(await reasoner_node(current, config(llm)))
    current.update(await anima_composer_node(current, config(llm)))
    current.update(await response_guard_node(current, config(llm)))
    assert len(llm.calls) == 2
    assert "normal_response" in llm.calls[0][0]["content"]
    assert "final_response" in llm.calls[1][0]["content"]
    assert current["response_text"] == "旅人，你好呀。"


@pytest.mark.asyncio
async def test_response_guard_hides_emotion_tag_but_preserves_raw_analysis_chunk() -> None:
    llm = SequencedLLM(
        [
            '{"normal_response":"晚上好","stance":"友好","humor":"","worldview":""}',
            '{"final_response":"晚上好呀[happy] 今天想喝点什么？","mood":"bright","affinity_delta":1}',
        ]
    )
    current = state()
    current.update(await reasoner_node(current, config(llm)))
    current.update(await anima_composer_node(current, config(llm)))
    current.update(await response_guard_node(current, config(llm)))

    assert current["response_text"] == "晚上好呀 今天想喝点什么？"
    assert current["response_chunks"] == ["晚上好呀[happy] 今天想喝点什么？"]


@pytest.mark.asyncio
async def test_composer_failure_uses_reasoner_with_no_third_call() -> None:
    llm = SequencedLLM(
        [
            '{"normal_response":"你好","stance":"友好","humor":"","worldview":""}',
            "RAISE",
        ]
    )
    current = state()
    current.update(await reasoner_node(current, config(llm)))
    current.update(await anima_composer_node(current, config(llm)))
    current.update(await response_guard_node(current, config(llm)))
    assert len(llm.calls) == 2
    assert current["response_text"] == "你好"
    assert current["metadata"]["dialogue_status"] == "composer_fallback"


@pytest.mark.asyncio
async def test_filtered_probe_makes_no_llm_call() -> None:
    llm = SequencedLLM([])
    current = state()
    current["metadata"] = {"is_inspection": True}
    current.update(await reasoner_node(current, config(llm)))
    current.update(await anima_composer_node(current, config(llm)))
    assert llm.calls == []
    assert current["metadata"]["dialogue_status"] == "filtered_probe"


@pytest.mark.asyncio
async def test_golden_history_keeps_developer_context_private() -> None:
    llm = SequencedLLM(['{"normal_response":"蓝玻璃","stance":"直接","humor":"","worldview":""}'])
    session = ConversationSessionState()
    session.commit(
        task_id="previous",
        user_text="本场暗号是蓝玻璃",
        final_response="收到。",
        actor_role="developer",
        source="developer_console",
    )
    runtime = {
        "configurable": {
            "service_context": SimpleNamespace(llm_engine=llm),
            "conversation_session": session,
        }
    }
    current = state()
    current["metadata"] = {
        "audience": "livestream",
        "actor_role": "viewer",
        "source": "bilibili:danmaku",
    }

    await reasoner_node(current, runtime)

    assert "可自然使用回答当前问题所必需的普通事实" in llm.calls[0][0]["content"]
    assert "复述整段开发者原文" in llm.calls[0][0]["content"]
    assert "后台私有上下文" in llm.calls[0][1]["content"]


@pytest.mark.asyncio
async def test_finalizer_commits_once_and_clears_scratch() -> None:
    llm = SequencedLLM(
        [
            '{"normal_response":"你好","stance":"友好","humor":"","worldview":""}',
            '{"final_response":"旅人，你好呀。","mood":"bright","affinity_delta":1}',
        ]
    )
    session = ConversationSessionState()
    runtime = {
        "configurable": {
            "service_context": SimpleNamespace(llm_engine=llm),
            "conversation_session": session,
        }
    }
    current = state()
    current.update(await reasoner_node(current, runtime))
    current.update(await anima_composer_node(current, runtime))
    current.update(await response_guard_node(current, runtime))
    current["metadata"]["text_ready_at"] = 1.0
    current["metadata"]["actor_role"] = "developer"
    current["metadata"]["source"] = "developer_console"
    current.update(await conversation_finalizer_node(current, runtime))
    assert current["turn_scratch"] == {}
    assert session.completed_window == (("你好", "旅人，你好呀。"),)
    assert session.mood == "bright"
    assert session.affinity == 51
    assert session.completed_turns[0].actor_role == "developer"
    assert session.completed_turns[0].source == "developer_console"
    duplicate = await conversation_finalizer_node(current, runtime)
    assert duplicate["metadata"]["conversation_committed"] is False
    assert session.completed_window == (("你好", "旅人，你好呀。"),)


@pytest.mark.asyncio
async def test_finalizer_clears_failure_scratch_without_commit() -> None:
    current = state()
    current["turn_scratch"] = {"internal": "must disappear"}
    current["error"] = "reasoner_failed"
    runtime = config(SequencedLLM([]))
    result = await conversation_finalizer_node(current, runtime)
    assert result["turn_scratch"] == {}
    assert result["metadata"]["conversation_committed"] is False


@pytest.mark.asyncio
async def test_finalizer_writes_only_selected_final_in_read_write_mode() -> None:
    memory = SimpleNamespace(encode=AsyncMock())
    session = ConversationSessionState()
    runtime = {
        "configurable": {
            "service_context": SimpleNamespace(
                memory_system=memory,
                config=SimpleNamespace(system=SimpleNamespace(long_term_memory_mode="read_write")),
            ),
            "conversation_session": session,
        }
    }
    current = state()
    current["response_text"] = "selected final"
    current["metadata"] = {"dialogue_status": "composer", "text_ready_at": 1.0}
    current.update(await conversation_finalizer_node(current, runtime))
    memory.encode.assert_awaited_once_with(
        user_input="你好",
        agent_response="selected final",
        emotion_vad=None,
        session_id="session",
    )


@pytest.mark.asyncio
async def test_proactive_finalizer_keeps_only_safe_session_context() -> None:
    memory = SimpleNamespace(encode=AsyncMock())
    provider = SequencedLLM([])
    session = ConversationSessionState(mood="bright", fatigue=20, affinity=71)
    runtime = {
        "configurable": {
            "service_context": SimpleNamespace(
                llm_engine=provider,
                memory_system=memory,
                config=SimpleNamespace(system=SimpleNamespace(long_term_memory_mode="read_write")),
            ),
            "conversation_session": session,
        }
    }
    current = state()
    current["user_text"] = "生成本轮直播主动话题。"
    current["response_text"] = "企鹅不会飞，因为没有买机票。"
    current["metadata"] = {
        "dialogue_status": "direct",
        "text_ready_at": 1.0,
        "source": "bilibili:proactive_topic",
        "actor_role": "host",
        "audience": "livestream",
    }

    result = await conversation_finalizer_node(current, runtime)

    assert result["metadata"]["conversation_committed"] is True
    assert session.completed_window == (
        ("[直播主持人自主发言触发，不是观众弹幕]", "企鹅不会飞，因为没有买机票。"),
    )
    assert "生成本轮直播主动话题" not in repr(session.completed_turns)
    assert (session.mood, session.fatigue, session.affinity) == ("bright", 20, 71)
    memory.encode.assert_not_awaited()


@pytest.mark.asyncio
async def test_minecraft_narration_is_not_committed_to_conversation_or_memory() -> None:
    memory = SimpleNamespace(encode=AsyncMock())
    provider = SequencedLLM([])
    session = ConversationSessionState()
    runtime = {
        "configurable": {
            "service_context": SimpleNamespace(
                llm_engine=provider,
                memory_system=memory,
                config=SimpleNamespace(system=SimpleNamespace(long_term_memory_mode="read_write")),
            ),
            "conversation_session": session,
        }
    }
    current = state()
    current["user_text"] = "根据当前公开 Minecraft 活动生成一句旁白。"
    current["response_text"] = "我正在确认橡木是否已经收集完成。"
    current["metadata"] = {
        "dialogue_status": "direct",
        "text_ready_at": 1.0,
        "source": "minecraft:narration",
        "actor_role": "host",
        "audience": "livestream",
    }

    result = await conversation_finalizer_node(current, runtime)

    assert result["metadata"]["conversation_committed"] is False
    assert session.completed_turns == ()
    memory.encode.assert_not_awaited()


@pytest.mark.parametrize(
    ("response", "metadata", "is_mock", "expected_commit"),
    [
        pytest.param(
            "real final",
            {"dialogue_status": "direct", "text_ready_at": 1.0},
            False,
            True,
            id="commit-real-delivered",
        ),
        pytest.param(
            "text survives media degradation",
            {
                "dialogue_status": "direct",
                "text_ready_at": 1.0,
                "degradation_reason": "tts_unavailable",
            },
            False,
            True,
            id="commit-tts-degraded",
        ),
        pytest.param(
            "probe",
            {"dialogue_status": "direct", "text_ready_at": 1.0, "is_probe": True},
            False,
            False,
            id="reject-probe",
        ),
        pytest.param(
            "inspection",
            {"dialogue_status": "direct", "text_ready_at": 1.0, "is_inspection": True},
            False,
            False,
            id="reject-inspection",
        ),
        pytest.param(
            "mock template",
            {"dialogue_status": "direct", "text_ready_at": 1.0},
            True,
            False,
            id="reject-mock",
        ),
        pytest.param(
            "timeout fallback",
            {"dialogue_status": "direct", "text_ready_at": 1.0, "error_type": "timeout"},
            False,
            False,
            id="reject-timeout",
        ),
        pytest.param(
            "partial response",
            {"dialogue_status": "direct", "text_ready_at": 1.0, "interrupted": True},
            False,
            False,
            id="reject-interrupted",
        ),
        pytest.param(
            "fallback response",
            {"dialogue_status": "direct", "text_ready_at": 1.0, "response_fallback": True},
            False,
            False,
            id="reject-fallback",
        ),
        pytest.param(
            "",
            {"dialogue_status": "direct", "text_ready_at": 1.0},
            False,
            False,
            id="reject-empty",
        ),
        pytest.param(
            "not publicly delivered",
            {"dialogue_status": "direct"},
            False,
            False,
            id="reject-undelivered",
        ),
        pytest.param(
            "rejected candidate",
            {"dialogue_status": "rejected", "text_ready_at": 1.0},
            False,
            False,
            id="reject-candidate",
        ),
        pytest.param(
            "我是一个 Mock LLM，用于测试和开发。",
            {"dialogue_status": "direct", "text_ready_at": 1.0},
            False,
            False,
            id="reject-unpersistable-template",
        ),
    ],
)
async def test_finalizer_submission_matrix(
    response: str,
    metadata: dict,
    is_mock: bool,
    expected_commit: bool,
) -> None:
    provider = SequencedLLM([])
    provider.is_mock_provider = is_mock
    session = ConversationSessionState()
    runtime = {
        "configurable": {
            "service_context": SimpleNamespace(llm_engine=provider),
            "conversation_session": session,
        }
    }
    current = state()
    current["response_text"] = response
    current["metadata"] = metadata

    result = await conversation_finalizer_node(current, runtime)

    assert result["metadata"]["conversation_committed"] is expected_commit
    assert bool(session.completed_window) is expected_commit


@pytest.mark.asyncio
async def test_concurrent_sessions_share_provider_without_state_or_identity_leak() -> None:
    llm = SharedSessionLLM()

    async def run(user: str, task: str):
        session = ConversationSessionState()
        runtime = {
            "configurable": {
                "service_context": SimpleNamespace(
                    llm_engine=llm,
                    config=SimpleNamespace(system=SimpleNamespace(long_term_memory_mode="off")),
                ),
                "conversation_session": session,
            }
        }
        current = create_initial_state("session-" + user, user_text=user, task_id=task)
        current["system_prompt"] = "你是 Anima。"
        current.update(await reasoner_node(current, runtime))
        current.update(await anima_composer_node(current, runtime))
        current.update(await response_guard_node(current, runtime))
        current["metadata"]["text_ready_at"] = 1.0
        current.update(await conversation_finalizer_node(current, runtime))
        return current, session

    (first, first_session), (second, second_session) = await asyncio.gather(
        run("alpha", "11111111-1111-4111-8111-111111111111"),
        run("beta", "22222222-2222-4222-8222-222222222222"),
    )
    assert first["response_text"] == "final:alpha"
    assert second["response_text"] == "final:beta"
    assert first["task_id"] != second["task_id"]
    assert first_session.completed_window == (("alpha", "final:alpha"),)
    assert second_session.completed_window == (("beta", "final:beta"),)
    assert llm.history == [{"role": "assistant", "content": "shared-provider-history"}]
    serialized_calls = [repr(call) for call in llm.calls]
    assert all(not ("alpha" in call and "beta" in call) for call in serialized_calls)
