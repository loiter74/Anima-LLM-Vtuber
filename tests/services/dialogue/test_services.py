from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from animetta.services.dialogue import AnimaComposer, DialogueServiceError, Reasoner
from animetta.services.dialogue.contracts import ComposerResult, ReasonerResult
from animetta.services.dialogue.guard import select_final_response
from animetta.services.dialogue.models import ComposerRequest, ReasonerRequest
from animetta.services.llm.interface import LLMInterface


class NativeMessagesLLM(LLMInterface):
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[dict[str, str]]] = []
        self.call_kwargs: list[dict] = []
        self.history = [{"role": "assistant", "content": "provider-owned"}]

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        self.call_kwargs.append(dict(kwargs))
        self.calls.append([dict(message) for message in messages])
        return self.responses.pop(0)

    async def chat(self, user_input: str, **kwargs) -> str:
        raise AssertionError("history-mutating chat() must not be used")

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


class HistoryOnlyLLM(NativeMessagesLLM):
    chat_messages = LLMInterface.chat_messages


def reasoner_request() -> ReasonerRequest:
    return ReasonerRequest(
        user_input="今天工作好累。",
        persona_prompt="你是 Anima。",
        completed_window=(("上一问", "上一答"),),
        roleplay_correction="保持角色口吻。",
    )


@pytest.mark.asyncio
async def test_reasoner_uses_explicit_messages_without_provider_history() -> None:
    raw = '{"normal_response":"先休息一下。","stance":"关心","humor":"轻微","worldview":"酒馆","extra":0}'
    llm = NativeMessagesLLM([raw.replace(',"extra":0', "")])
    original = list(llm.history)

    result = await Reasoner(llm).reason(reasoner_request())

    assert result.normal_response == "先休息一下。"
    assert llm.history == original
    assert [message["role"] for message in llm.calls[0]] == ["system", "user"]
    assert '"completed_window":[["上一问","上一答"]]' in llm.calls[0][1]["content"]
    assert "normal_response" in llm.calls[0][0]["content"]
    assert llm.call_kwargs == [{"temperature": 0, "response_format": {"type": "json_object"}}]


@pytest.mark.asyncio
async def test_reasoner_rejects_provider_without_native_chat_messages() -> None:
    with pytest.raises(DialogueServiceError) as exc:
        await Reasoner(HistoryOnlyLLM([])).reason(reasoner_request())
    assert exc.value.code == "history_unsafe"


@pytest.mark.asyncio
async def test_composer_receives_reasoner_and_ephemeral_state_explicitly() -> None:
    llm = NativeMessagesLLM(
        ['{"final_response":"累了就先在酒馆趴一会儿。","mood":"tired","affinity_delta":1}']
    )
    request = ComposerRequest(
        user_input="今天工作好累。",
        persona_prompt="你是 Anima。",
        reasoner=ReasonerResult(
            normal_response="先休息一下。", stance="关心", humor="轻微", worldview="酒馆"
        ),
        completed_window=(("上一问", "上一答"),),
        mood="neutral",
        fatigue=20,
        affinity=50,
    )

    result = await AnimaComposer(llm).compose(request)

    assert result.affinity_delta == 1
    prompt = llm.calls[0][-1]["content"]
    assert '"fatigue":20' in prompt
    assert '"normal_response":"先休息一下。"' in prompt
    assert llm.history == [{"role": "assistant", "content": "provider-owned"}]


def test_guard_prefers_valid_composer_without_another_llm_call() -> None:
    reasoner = ReasonerResult(normal_response="普通回答", stance="中立", humor="", worldview="")
    composer = ComposerResult(final_response="角色回答", mood="bright", affinity_delta=1)
    result = select_final_response(reasoner, composer)
    assert result.text == "角色回答"
    assert result.source == "composer"


def test_guard_falls_back_without_leaking_rejected_candidate() -> None:
    reasoner = ReasonerResult(normal_response="普通回答", stance="中立", humor="", worldview="")
    result = select_final_response(reasoner, None, rejection_code="schema_invalid")
    assert result.text == "普通回答"
    assert result.source == "composer_fallback"
    assert result.rejection_code == "schema_invalid"
    assert "角色" not in repr(result)
