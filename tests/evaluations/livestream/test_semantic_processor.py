from __future__ import annotations

import json

import pytest

from evaluations.livestream.cleaning import ContextMessage, SemanticRequest
from evaluations.livestream.semantic import (
    StrictLLMSemanticProcessor,
    create_deepseek_semantic_processor,
)


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[dict[str, str]], dict[str, object]]] = []
        self.closed = False

    async def chat_messages(
        self,
        messages: list[dict[str, str]],
        **kwargs: object,
    ) -> str:
        self.calls.append((messages, kwargs))
        return self.responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def _request(sequence: int = 7) -> SemanticRequest:
    return SemanticRequest(
        sequence=sequence,
        text="that one?",
        context_before=(ContextMessage(6, 1_000, "刚才应该走左边"),),
        context_after=(ContextMessage(8, 3_000, "然后打开宝箱"),),
    )


def _response(sequence: int = 7, *, text_zh: str = "你指的是刚才那个吗？") -> str:
    return json.dumps(
        {
            "decisions": [
                {
                    "sequence": sequence,
                    "keep": True,
                    "intent": "context_reply",
                    "text_zh": text_zh,
                    "reason": "",
                },
            ],
        },
        ensure_ascii=False,
    )


async def test_strict_processor_uses_zero_temperature_and_structured_json() -> None:
    llm = FakeLLM([_response()])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    decisions = await processor.process_batch([_request()])

    assert decisions[0].text_zh == "你指的是刚才那个吗？"
    messages, kwargs = llm.calls[0]
    assert kwargs["temperature"] == 0
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "that one?" in messages[1]["content"]
    assert "刚才应该走左边" in messages[1]["content"]


async def test_prompt_context_does_not_expose_decision_like_sequence_fields() -> None:
    llm = FakeLLM([_response()])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    await processor.process_batch([_request()])

    payload = json.loads(llm.calls[0][0][1]["content"])
    item = payload["items"][0]
    assert item["sequence"] == 7
    assert item["context_before"] == [{"offset_ms": 1000, "text": "刚才应该走左边"}]
    assert item["context_after"] == [{"offset_ms": 3000, "text": "然后打开宝箱"}]


async def test_strict_processor_declares_the_exact_decision_schema() -> None:
    llm = FakeLLM([_response()])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    await processor.process_batch([_request()])

    system_prompt = llm.calls[0][0][0]["content"]
    for field in ('"sequence"', '"keep"', '"intent"', '"text_zh"', '"reason"'):
        assert field in system_prompt
    assert "exactly one decision for every input item" in system_prompt


async def test_strict_processor_retries_invalid_responses_up_to_three_times() -> None:
    llm = FakeLLM(["not json", '{"decisions": []}', _response()])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    decisions = await processor.process_batch([_request()])

    assert decisions[0].sequence == 7
    assert len(llm.calls) == 3


async def test_strict_processor_retries_with_safe_validation_feedback() -> None:
    llm = FakeLLM(["not json", _response()])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    await processor.process_batch([_request()])

    first_messages = llm.calls[0][0]
    second_messages = llm.calls[1][0]
    assert len(second_messages) == len(first_messages)
    assert [message["role"] for message in second_messages] == ["system", "user"]
    feedback = second_messages[0]["content"]
    assert "failed strict validation" in feedback
    assert "JSONDecodeError" in feedback
    assert "not json" not in feedback
    assert json.loads(second_messages[-1]["content"])["items"][0]["sequence"] == 7


async def test_strict_processor_gives_actionable_chinese_repair_feedback() -> None:
    llm = FakeLLM(
        [
            _response(text_zh="Brain but thought AI Dentge"),
            _response(text_zh="大脑？但我以为是 AI Dentge。"),
        ],
    )
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    await processor.process_batch([_request()])

    feedback = llm.calls[1][0][0]["content"]
    assert "Translate every ordinary English word" in feedback
    assert "at least one Chinese character" in feedback
    assert "Hi Alice!" in feedback
    assert "keep=false" in feedback


async def test_strict_processor_localizes_embedded_emote_in_chinese_result() -> None:
    llm = FakeLLM(
        [_response(text_zh="她最后会杀了Party Snax，对吧？Sadge")],
    )
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    decisions = await processor.process_batch([_request()])

    assert decisions[0].text_zh == "她最后会杀了Party Snax，对吧？（难过）"
    assert len(llm.calls) == 1


async def test_strict_processor_localizes_embedded_alert_emote() -> None:
    llm = FakeLLM([_response(text_zh="DinkDonk Vedal 帮她")])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    decisions = await processor.process_batch([_request()])

    assert decisions[0].text_zh == "（提醒） Vedal 帮她"
    assert len(llm.calls) == 1


async def test_strict_processor_localizes_embedded_urge_emote() -> None:
    llm = FakeLLM([_response(text_zh="tutelBedge 醒醒，Vedal")])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    decisions = await processor.process_batch([_request()])

    assert decisions[0].text_zh == "（催促） 醒醒，Vedal"
    assert len(llm.calls) == 1


async def test_strict_processor_localizes_embedded_laughter_emote() -> None:
    llm = FakeLLM([_response(text_zh="试试ALT+F4 xdd")])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    decisions = await processor.process_batch([_request()])

    assert decisions[0].text_zh == "试试ALT+F4 （笑）"
    assert len(llm.calls) == 1


async def test_strict_processor_localizes_embedded_sound_effect_terms() -> None:
    llm = FakeLLM(
        [
            _response(
                text_zh="她旧音效少了吗？比如Poke、jumpscare、groan tube等？",
            ),
        ],
    )
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    decisions = await processor.process_batch([_request()])

    assert decisions[0].text_zh == "她旧音效少了吗？比如戳戳、突脸惊吓、呻吟管等？"
    assert len(llm.calls) == 1


async def test_strict_processor_retries_only_invalid_items_and_merges_results() -> None:
    first_response = json.dumps(
        {
            "decisions": [
                json.loads(_response(sequence=7, text_zh="still English"))["decisions"][0],
                json.loads(_response(sequence=9, text_zh="这条已经是中文"))["decisions"][0],
            ],
        },
        ensure_ascii=False,
    )
    llm = FakeLLM([first_response, _response(sequence=7, text_zh="这条已修复为中文")])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    decisions = await processor.process_batch([_request(7), _request(9)])

    assert [decision.sequence for decision in decisions] == [7, 9]
    retry_payload = json.loads(llm.calls[1][0][1]["content"])
    assert [item["sequence"] for item in retry_payload["items"]] == [7]


async def test_strict_processor_fails_after_three_malformed_responses() -> None:
    llm = FakeLLM(["not json", "still bad", '{"decisions": []}'])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    with pytest.raises(
        RuntimeError,
        match="semantic decision sequences do not reconcile",
    ):
        await processor.process_batch([_request()])

    assert len(llm.calls) == 3


async def test_strict_processor_rejects_non_chinese_retained_text() -> None:
    llm = FakeLLM([_response(text_zh="hello there my friend")] * 3)
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    with pytest.raises(RuntimeError, match="sequence=7"):
        await processor.process_batch([_request()])


async def test_production_policy_audits_non_chinese_text_as_drop_after_three_attempts() -> None:
    llm = FakeLLM([_response(text_zh="hello there my friend")] * 3)
    processor = StrictLLMSemanticProcessor(
        llm,
        provider_name="deepseek",
        non_chinese_policy="drop",
    )

    decisions = await processor.process_batch([_request()])

    assert len(llm.calls) == 3
    assert decisions[0].keep is False
    assert decisions[0].intent == ""
    assert decisions[0].text_zh == ""
    assert decisions[0].reason == "non_chinese_after_retries"


async def test_strict_processor_reports_every_non_chinese_sequence_in_the_batch() -> None:
    response = json.dumps(
        {
            "decisions": [
                {
                    "sequence": sequence,
                    "keep": True,
                    "intent": "comment",
                    "text_zh": "still an English phrase",
                    "reason": "",
                }
                for sequence in (7, 9)
            ],
        },
    )
    processor = StrictLLMSemanticProcessor(
        FakeLLM([response] * 3),
        provider_name="deepseek",
    )

    with pytest.raises(RuntimeError, match="sequences=7,9"):
        await processor.process_batch([_request(7), _request(9)])


async def test_strict_processor_reports_missing_and_unexpected_sequences() -> None:
    response = _response(sequence=7)
    processor = StrictLLMSemanticProcessor(
        FakeLLM([response] * 3),
        provider_name="deepseek",
    )

    with pytest.raises(
        RuntimeError,
        match=r"missing=9; unexpected=none; duplicates=none",
    ):
        await processor.process_batch([_request(7), _request(9)])


async def test_strict_processor_accepts_empty_intent_for_a_dropped_item() -> None:
    response = json.dumps(
        {
            "decisions": [
                {
                    "sequence": 7,
                    "keep": False,
                    "intent": "",
                    "text_zh": "",
                    "reason": "unrecognized_intent",
                },
            ],
        },
    )
    processor = StrictLLMSemanticProcessor(
        FakeLLM([response] * 3),
        provider_name="deepseek",
    )

    decisions = await processor.process_batch([_request()])

    assert decisions[0].keep is False
    assert decisions[0].intent == ""


async def test_strict_processor_identifies_the_invalid_decision_field_type() -> None:
    response = json.loads(_response())
    response["decisions"][0]["reason"] = None
    llm = FakeLLM([json.dumps(response)] * 3)
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    with pytest.raises(RuntimeError, match="reason.*string.*NoneType"):
        await processor.process_batch([_request()])


def test_strict_processor_rejects_mock_provider() -> None:
    with pytest.raises(ValueError, match="mock"):
        StrictLLMSemanticProcessor(FakeLLM([]), provider_name="mock")


async def test_strict_processor_rejects_batches_over_forty() -> None:
    processor = StrictLLMSemanticProcessor(FakeLLM([]), provider_name="deepseek")

    with pytest.raises(ValueError, match="40"):
        await processor.process_batch([_request(sequence) for sequence in range(41)])


class FakeProvider:
    def __init__(self, provider_type: str = "deepseek", model: str = "deepseek-v4-flash") -> None:
        self.type = provider_type
        self.model = model


class FakeConfiguredProvider:
    def __init__(self, provider_type: str = "deepseek") -> None:
        self.type = provider_type
        self.model = "deepseek-v4-flash"
        self.provider = FakeProvider(provider_type)

    def typed_config(self) -> FakeProvider:
        return self.provider


def test_factory_loads_selected_deepseek_with_strict_creation(tmp_path) -> None:
    manifest = tmp_path / "animetta.yaml"
    loaded: list[tuple[object, str, str]] = []
    created: list[tuple[object, str, bool]] = []
    llm = FakeLLM([])

    def load_config(path, *, profile, category):
        loaded.append((path, profile, category))
        return FakeConfiguredProvider()

    def create_llm(config, system_prompt="", *, strict=False):
        created.append((config, system_prompt, strict))
        return llm

    processor = create_deepseek_semantic_processor(
        manifest,
        profile="production",
        config_loader=load_config,
        llm_creator=create_llm,
    )

    assert loaded == [(manifest, "production", "llm")]
    assert created == [(processor.config, "", True)]
    assert processor.provider_name == "deepseek"
    assert processor.model_name == "deepseek-v4-flash"
    assert processor.non_chinese_policy == "drop"


def test_factory_rejects_non_deepseek_provider(tmp_path) -> None:
    with pytest.raises(ValueError, match="DeepSeek"):
        create_deepseek_semantic_processor(
            tmp_path / "animetta.yaml",
            profile="production",
            config_loader=lambda *_args, **_kwargs: FakeConfiguredProvider("mock"),
            llm_creator=lambda *_args, **_kwargs: FakeLLM([]),
        )


def test_factory_resolves_only_llm_environment_for_cleaning(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_TTS_API_KEY", raising=False)

    processor = create_deepseek_semantic_processor(
        "config/animetta.yaml",
        profile="production",
        llm_creator=lambda *_args, **_kwargs: FakeLLM([]),
    )

    assert processor.provider_name == "deepseek"
    assert processor.config.type == "deepseek"


async def test_processor_closes_underlying_llm() -> None:
    llm = FakeLLM([])
    processor = StrictLLMSemanticProcessor(llm, provider_name="deepseek")

    await processor.close()

    assert llm.closed is True
