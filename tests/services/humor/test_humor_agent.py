from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from animetta.services.humor import (
    HumorAgent,
    HumorConfig,
    HumorFallbackReason,
    HumorRewriteRequest,
)
from animetta.services.humor.filters import validate_humor_candidate
from animetta.services.humor.history_safe import chat_messages_history_safe
from animetta.services.humor.metadata import (
    HUMOR_CANDIDATE_KEY,
    HUMOR_VALIDATION_KEY,
    candidate_from_metadata,
    record_humor_candidate,
    record_humor_validation,
)
from animetta.services.humor.parser import HumorParseError, parse_humor_result
from animetta.services.llm.interface import LLMInterface


def _raw_humor_json(**overrides) -> str:
    data = {
        "scene": "work_fatigue",
        "emotion": "tired_complaint",
        "humor_anchor": "work as dungeon, fatigue as durability loss",
        "worldview_mapping": "office = low-budget demon castle",
        "style": "self-enhancing + affiliative",
        "candidate_response": "今日工位副本强度超标，灵魂耐久掉得比手机电量还快。",
        "risk": "safe",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _request(config: HumorConfig | None = None) -> HumorRewriteRequest:
    return HumorRewriteRequest(
        user_input="上班好累",
        normal_response="工作压力大时会感到疲惫，需要休息。",
        persona={"name": "Anima"},
        metadata={"channel": "danmaku"},
        config=config or HumorConfig(enabled=True),
    )


class _NativeLLM(LLMInterface):
    def __init__(self, response: str = "") -> None:
        self.response = response or _raw_humor_json()
        self.history: list[dict] = [{"role": "user", "content": "hello"}]
        self._chat_mock = AsyncMock(side_effect=AssertionError("chat() should not be called"))

    async def chat(self, user_input: str, **kwargs) -> str:
        return await self._chat_mock(user_input, **kwargs)

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        self.last_messages = messages
        return self.response

    async def chat_stream(self, user_input: str, **kwargs):
        yield "chunk"

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def get_history(self) -> list[dict]:
        return [msg.copy() for msg in self.history]

    def clear_history(self) -> None:
        self.history.clear()

    async def close(self) -> None:
        pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        pass

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass


class _FallbackLLM(LLMInterface):
    def __init__(self, response: str = "") -> None:
        self.response = response or _raw_humor_json()
        self._history: list[dict] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        self.chat_calls = 0

    async def chat(self, user_input: str, **kwargs) -> str:
        self.chat_calls += 1
        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": self.response})
        return self.response

    async def chat_stream(self, user_input: str, **kwargs):
        yield "chunk"

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def get_history(self) -> list[dict]:
        return [msg.copy() for msg in self._history]

    def clear_history(self) -> None:
        self._history.clear()

    async def close(self) -> None:
        pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        pass

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass


class _UnsafeLLM(LLMInterface):
    def __init__(self) -> None:
        self._chat_mock = AsyncMock(return_value=_raw_humor_json())

    async def chat(self, user_input: str, **kwargs) -> str:
        return await self._chat_mock(user_input, **kwargs)

    async def chat_stream(self, user_input: str, **kwargs):
        yield "chunk"

    def set_system_prompt(self, prompt: str) -> None:
        pass

    def get_history(self) -> list[dict]:
        raise NotImplementedError("no history")

    def clear_history(self) -> None:
        raise NotImplementedError("no history")

    async def close(self) -> None:
        pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        pass

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass


class _SlowNativeLLM(_NativeLLM):
    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        await asyncio.sleep(1)
        return self.response


class TestHumorConfig:
    def test_defaults_are_conservative(self):
        cfg = HumorConfig()
        assert cfg.enabled is False
        assert cfg.candidate_count == 1
        assert "affiliative" in cfg.allowed_styles

    def test_explicit_enabled_config(self):
        cfg = HumorConfig(enabled=True, max_candidate_chars=90, worldview_hints=["cyber tavern"])
        assert cfg.enabled is True
        assert cfg.max_candidate_chars == 90
        assert cfg.worldview_hints == ["cyber tavern"]


class TestHistorySafeCalls:
    @pytest.mark.asyncio
    async def test_native_chat_messages_does_not_call_chat(self):
        llm = _NativeLLM()
        result = await chat_messages_history_safe(llm, [{"role": "user", "content": "x"}])
        assert result.content is not None
        llm._chat_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_restores_history(self):
        llm = _FallbackLLM()
        before = llm.get_history()
        result = await chat_messages_history_safe(llm, [{"role": "user", "content": "x"}])
        assert result.content is not None
        assert llm.chat_calls == 1
        assert llm.get_history() == before

    @pytest.mark.asyncio
    async def test_unsafe_history_is_skipped(self):
        llm = _UnsafeLLM()
        result = await chat_messages_history_safe(llm, [{"role": "user", "content": "x"}])
        assert result.content is None
        assert result.fallback_reason == HumorFallbackReason.HISTORY_UNSAFE
        llm._chat_mock.assert_not_called()


class TestParsingAndFilters:
    def test_parse_valid_json(self):
        result = parse_humor_result(_raw_humor_json(), _request())
        assert result.scene == "work_fatigue"
        assert result.candidate_response

    def test_parse_missing_field_raises_stable_reason(self):
        with pytest.raises(HumorParseError) as exc:
            parse_humor_result(json.dumps({"scene": "x"}), _request())
        assert exc.value.reason == HumorFallbackReason.MISSING_FIELD

    def test_filter_rejects_too_long_candidate(self):
        result = parse_humor_result(_raw_humor_json(candidate_response="x" * 50), _request())
        reason = validate_humor_candidate(result, HumorConfig(enabled=True, max_candidate_chars=30))
        assert reason == HumorFallbackReason.CANDIDATE_TOO_LONG

    def test_filter_rejects_customer_service_phrase(self):
        result = parse_humor_result(
            _raw_humor_json(candidate_response="很抱歉，作为一个AI，我无法完成这个幽默请求。"),
            _request(),
        )
        reason = validate_humor_candidate(result, HumorConfig(enabled=True))
        assert reason == HumorFallbackReason.CUSTOMER_SERVICE_PHRASE

    def test_metadata_is_compact(self):
        result = parse_humor_result(_raw_humor_json(), _request()).accept()
        metadata = result.to_metadata()
        assert metadata["accepted"] is True
        assert metadata["style"]
        assert "candidate_response" not in metadata

    def test_candidate_handoff_metadata_round_trips_full_candidate(self):
        result = parse_humor_result(_raw_humor_json(), _request())
        metadata = record_humor_candidate({"trace": "abc"}, result)

        restored = candidate_from_metadata(metadata)

        assert metadata["trace"] == "abc"
        assert restored is not None
        assert restored.candidate_response == result.candidate_response
        assert restored.normal_response == result.normal_response
        assert restored.accepted is False
        assert HUMOR_CANDIDATE_KEY in metadata

    def test_validation_metadata_records_final_decision(self):
        result = parse_humor_result(_raw_humor_json(), _request()).reject(
            HumorFallbackReason.CUSTOMER_SERVICE_PHRASE
        )
        metadata = record_humor_validation({}, result)

        assert metadata[HUMOR_VALIDATION_KEY]["accepted"] is False
        assert metadata[HUMOR_VALIDATION_KEY]["fallback_reason"] == "customer_service_phrase"


class TestHumorAgent:
    @pytest.mark.asyncio
    async def test_generate_candidate_does_not_validate_or_accept(self):
        llm = _NativeLLM(response=_raw_humor_json(risk="unsafe"))
        result = await HumorAgent(llm).generate_candidate(_request())

        assert result.accepted is False
        assert result.fallback_reason is None
        assert result.candidate_response
        assert result.risk == "unsafe"

    @pytest.mark.asyncio
    async def test_successful_rewrite(self):
        llm = _NativeLLM()
        result = await HumorAgent(llm).rewrite(_request())
        assert result.accepted is True
        assert "工位副本" in result.visible_response
        assert result.fallback_reason is None

    @pytest.mark.asyncio
    async def test_disabled_falls_back(self):
        result = await HumorAgent(_NativeLLM()).rewrite(_request(HumorConfig()))
        assert result.accepted is False
        assert result.enabled is False
        assert result.fallback_reason == HumorFallbackReason.DISABLED
        assert result.visible_response == result.normal_response

    @pytest.mark.asyncio
    async def test_timeout_falls_back(self):
        result = await HumorAgent(_SlowNativeLLM()).rewrite(
            _request(HumorConfig(enabled=True, timeout_seconds=0.001))
        )
        assert result.fallback_reason == HumorFallbackReason.LLM_TIMEOUT

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self):
        result = await HumorAgent(_NativeLLM(response="not json")).rewrite(_request())
        assert result.fallback_reason == HumorFallbackReason.INVALID_JSON
        assert result.visible_response == result.normal_response

    @pytest.mark.asyncio
    async def test_unsafe_candidate_rejected(self):
        llm = _NativeLLM(response=_raw_humor_json(risk="unsafe"))
        result = await HumorAgent(llm).rewrite(_request())
        assert result.accepted is False
        assert result.fallback_reason == HumorFallbackReason.UNSAFE_RISK

    @pytest.mark.asyncio
    async def test_customer_service_candidate_rejected(self):
        llm = _NativeLLM(
            response=_raw_humor_json(
                candidate_response="很抱歉，如果你还有其他问题，我会继续为你服务。"
            )
        )
        result = await HumorAgent(llm).rewrite(_request())
        assert result.accepted is False
        assert result.fallback_reason == HumorFallbackReason.CUSTOMER_SERVICE_PHRASE
