from __future__ import annotations

"""Tests for stateless subtitle translation helper.

Covers the behavioral contracts from design.md Decision 3 and spec requirements:
- Subtitle translation uses response_text as input, not a second authored answer.
- Requires chat_messages() and never calls history-mutating chat().
- Providers without an explicit-messages implementation are skipped.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.orchestration.graph.subtitle_translator import (
    strip_runtime_markers,
    translate_subtitle_text,
)
from animetta.services.llm.interface import LLMInterface
from animetta.tracing.proxy import TracingProxy

# ── Helpers ──────────────────────────────────────────────────────


class _NativeChatMessagesLLM(LLMInterface):
    """Fake LLM with native chat_messages() override (safe, no history mutation)."""

    def __init__(self, translation: str = "translated text"):
        self._translation = translation
        # Override chat_messages as a non-abstract mock
        self._chat_messages_mock = AsyncMock(return_value=translation)
        self._chat_mock = AsyncMock(side_effect=AssertionError("chat() should not be called"))
        self.chat_stream = AsyncMock()
        self.set_system_prompt = MagicMock()
        self.get_history = MagicMock(return_value=[])
        self.clear_history = MagicMock()
        self.close = AsyncMock()
        self.handle_interrupt = MagicMock()
        self.set_memory_from_history = MagicMock()

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        return await self._chat_messages_mock(messages, **kwargs)

    @property
    def chat_messages_calls(self):
        return self._chat_messages_mock.call_args_list

    async def chat(self, user_input: str, **kwargs) -> str:
        return await self._chat_mock(user_input, **kwargs)

    async def chat_stream(self, user_input: str, **kwargs):
        yield "chunk"

    def set_system_prompt(self, prompt: str) -> None:
        pass

    def get_history(self) -> list[dict]:
        return []

    def clear_history(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        pass

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass


class _FallbackLLM(LLMInterface):
    """Legacy fake that only implements history-mutating chat()."""

    def __init__(self, translation: str = "translated text"):
        self._translation = translation
        self._history: list[dict] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        # chat() records calls for assertion
        self._chat_calls: list[str] = []
        self._chat_mock = AsyncMock(side_effect=self._record_chat)
        self.chat_stream = AsyncMock()
        self.set_system_prompt = MagicMock()
        self.get_history = MagicMock(return_value=list(self._history))
        self.clear_history = MagicMock()
        self.close = AsyncMock()
        self.handle_interrupt = MagicMock()
        self.set_memory_from_history = MagicMock()

    async def _record_chat(self, user_input: str, **kwargs) -> str:
        self._chat_calls.append(user_input)
        return self._translation

    async def chat(self, user_input: str, **kwargs) -> str:
        return await self._chat_mock(user_input, **kwargs)

    async def chat_stream(self, user_input: str, **kwargs):
        yield "chunk"

    def set_system_prompt(self, prompt: str) -> None:
        pass

    def get_history(self) -> list[dict]:
        return self._history

    def clear_history(self) -> None:
        self._history.clear()

    async def close(self) -> None:
        pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        pass

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass


class _UnsafeLLM(LLMInterface):
    """Fake LLM with no get_history/set_system_prompt (unsafe for fallback)."""

    def __init__(self):
        self._chat_mock = AsyncMock(return_value="translated")
        self.chat_stream = AsyncMock()
        self.close = AsyncMock()
        self.handle_interrupt = MagicMock()
        self.set_memory_from_history = MagicMock()

    async def chat(self, user_input: str, **kwargs) -> str:
        return await self._chat_mock(user_input, **kwargs)

    async def chat_stream(self, user_input: str, **kwargs):
        yield "chunk"

    def set_system_prompt(self, prompt: str) -> None:
        pass

    def get_history(self) -> list[dict]:
        raise NotImplementedError("This LLM has no history")

    def clear_history(self) -> None:
        raise NotImplementedError("This LLM has no history")

    async def close(self) -> None:
        pass

    def handle_interrupt(self, heard_response: str = "") -> None:
        pass

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass


# ── Task 1.1: Translation uses response_text, not a second answer ──


class TestTranslationUsesResponseText:
    """Prove subtitle translation receives the main response_text as input
    and does not produce a second authored answer."""

    @pytest.mark.asyncio
    async def test_translator_receives_response_text_content(self):
        """The translator should be called with the response_text content,
        not a creative prompt that could generate a new answer."""
        llm = _NativeChatMessagesLLM(translation="translated response text")

        result = await translate_subtitle_text(
            llm, "主播你又卡了", source_lang="Chinese", target_lang="English"
        )

        assert result == "translated response text"
        # Verify chat_messages was called with isolated translation messages
        calls = llm.chat_messages_calls
        assert len(calls) == 1
        messages = calls[0][0][0]
        # System prompt should be translation-specific, not Anima persona
        assert "subtitle translator" in messages[0]["content"].lower()
        # User message should contain the source text
        assert "主播你又卡了" in messages[1]["content"]

    @pytest.mark.asyncio
    async def test_translator_does_not_answer_user(self):
        """The translation system prompt explicitly forbids answering the user."""
        llm = _NativeChatMessagesLLM()

        await translate_subtitle_text(llm, "你好吗", "Chinese", "English")

        calls = llm.chat_messages_calls
        messages = calls[0][0][0]
        system_prompt = messages[0]["content"].lower()
        assert "do not" in system_prompt or "do NOT" in messages[0]["content"]
        assert "answer" in system_prompt

    @pytest.mark.asyncio
    async def test_empty_cleaned_text_returns_none(self):
        """When source text is only markers, return None (no translation)."""
        llm = _NativeChatMessagesLLM()
        result = await translate_subtitle_text(llm, "[happy][sad]", "Chinese", "English")
        assert result is None
        assert len(llm.chat_messages_calls) == 0


class TestTargetLanguageControl:
    """Prove subtitle translation gives the LLM explicit language constraints."""

    @pytest.mark.asyncio
    async def test_prompt_names_source_and_target_languages(self):
        """The prompt should explicitly say which language to translate into."""
        llm = _NativeChatMessagesLLM(translation="Good evening, traveler.")

        await translate_subtitle_text(
            llm,
            "晚上好，旅人。",
            source_lang="Chinese",
            target_lang="English",
        )

        messages = llm.chat_messages_calls[0][0][0]
        combined_prompt = "\n".join(message["content"] for message in messages)
        assert "Chinese" in combined_prompt
        assert "English" in combined_prompt
        assert "target language" in combined_prompt.lower()

    @pytest.mark.asyncio
    async def test_translation_uses_deterministic_temperature(self):
        """Subtitle translation should be low-variance, not creative."""
        llm = _NativeChatMessagesLLM(translation="Good evening, traveler.")

        await translate_subtitle_text(llm, "晚上好，旅人。", "Chinese", "English")

        kwargs = llm.chat_messages_calls[0][1]
        assert kwargs["temperature"] == 0

    @pytest.mark.asyncio
    async def test_thirteen_subtitle_turns_keep_english_target_constraints(self):
        """Subtitle translation should keep explicit English constraints over 13 turns."""
        llm = _NativeChatMessagesLLM(translation="English subtitle")
        source_lines = [
            "旅人，我记得，上一句你是在试探我的记忆力。",
            "确实，这声哈哈把酒馆的夜班灯都笑亮了。",
            "今晚菜单有糖醋排骨、麻婆豆腐。",
            "讲真，召唤者X说要给我涨工资。",
            "刚才那个梗的重点是，AI 做梦都逃不过加班。",
            "别慌，这么多牛再刷下去，酒馆后厨都要改牧场了。",
            "菜单这种东西当然有，只是本店目前主要供应想象力和热水。",
            "如果要我记，我会说你刚才已经把酒馆菜单和冷笑话都翻过一遍了。",
            "那当然，我只是把存在感调成了省电模式。",
            "这个嘛，大概是酒馆 Wi-Fi 把我的吐槽包拆成了两半。",
            "行，夜还长，杯子也没空，继续坐着聊。",
            "轮到我把话接住，然后假装这一切都很从容。",
            "第十三轮也稳住了，旅人，这酒馆的灯还亮着。",
        ]

        for line in source_lines:
            assert (
                await translate_subtitle_text(llm, line, "Chinese", "English") == "English subtitle"
            )

        assert len(llm.chat_messages_calls) == 13
        for call in llm.chat_messages_calls:
            messages = call[0][0]
            kwargs = call[1]
            combined_prompt = "\n".join(message["content"] for message in messages)
            assert "Chinese" in combined_prompt
            assert "English" in combined_prompt
            assert "target language" in combined_prompt.lower()
            assert kwargs["temperature"] == 0


# ── Task 1.2: Prefers chat_messages(), does not call chat() ──


class TestPrefersChatMessages:
    """Prove translation uses chat_messages() and does not call
    history-mutating chat() when a native message-based path is available."""

    @pytest.mark.asyncio
    async def test_native_chat_messages_used(self):
        """When LLM has native chat_messages(), it should be used."""
        llm = _NativeChatMessagesLLM(translation="You're lagging again, streamer")

        result = await translate_subtitle_text(llm, "主播你又卡了", "Chinese", "English")

        assert result == "You're lagging again, streamer"
        assert len(llm.chat_messages_calls) == 1

    @pytest.mark.asyncio
    async def test_chat_not_called_when_native_messages_available(self):
        """chat() must NOT be called when chat_messages() is native."""
        llm = _NativeChatMessagesLLM()

        await translate_subtitle_text(llm, "测试文本", "Chinese", "English")

        # chat_messages was called
        assert len(llm.chat_messages_calls) == 1
        # chat() raises AssertionError if called, so reaching here means it wasn't

    @pytest.mark.asyncio
    async def test_translation_system_prompt_is_subtitle_specific(self):
        """The system prompt should be for subtitle translation, not Anima persona."""
        llm = _NativeChatMessagesLLM()

        await translate_subtitle_text(llm, "你好", "Chinese", "English")

        calls = llm.chat_messages_calls
        messages = calls[0][0][0]
        system_content = messages[0]["content"]
        # Should mention subtitle/translation purpose
        assert "subtitle" in system_content.lower() or "translat" in system_content.lower()
        # Should NOT be the full Anima persona prompt
        assert "anima" in system_content.lower()  # name is ok
        assert "好感度" not in system_content  # no affinity system
        assert "即兴闲聊" not in system_content  # no improvisation prompt

    @pytest.mark.asyncio
    async def test_native_chat_messages_used_through_tracing_proxy(self):
        """TracingProxy should not hide the wrapped LLM's native chat_messages()."""
        llm = _NativeChatMessagesLLM(translation="Not me lagging, the tavern has bugs again.")
        proxy = TracingProxy(llm, service_name="llm")

        result = await translate_subtitle_text(
            proxy, "不是我卡了，是酒馆后厨又进虫子了。", "Chinese", "English"
        )

        assert result == "Not me lagging, the tavern has bugs again."
        assert len(llm.chat_messages_calls) == 1


# ── Providers without native explicit messages are skipped ──


class TestFallbackBehavior:
    """Prove translation never falls back to shared provider history."""

    @pytest.mark.asyncio
    async def test_legacy_fallback_is_rejected_even_with_restorable_history(self):
        """Shared-history restoration is no longer an accepted provider contract."""
        llm = _FallbackLLM(translation="lagging again")

        result = await translate_subtitle_text(llm, "主播你又卡了", "Chinese", "English")

        assert result is None
        llm._chat_mock.assert_not_called()
        llm.clear_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsafe_llm_skips_translation(self):
        """When LLM lacks history safety, translation should be skipped."""
        llm = _UnsafeLLM()

        result = await translate_subtitle_text(llm, "主播你又卡了", "Chinese", "English")

        assert result is None
        # chat() should NOT have been called
        llm._chat_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_native_messages_returns_none_on_empty_result(self):
        """When translation returns empty, return None."""
        llm = _NativeChatMessagesLLM(translation="")

        result = await translate_subtitle_text(llm, "测试", "Chinese", "English")

        assert result is None


# ── Runtime marker stripping ──


class TestStripRuntimeMarkers:
    """Prove runtime markers are stripped before translation."""

    def test_emotion_tags_stripped(self):
        assert strip_runtime_markers("[happy]你好啊[sad]") == "你好啊"

    def test_affinity_markers_stripped(self):
        assert strip_runtime_markers("你好[affinity:75]世界") == "你好世界"

    def test_generic_runtime_markers_stripped(self):
        assert strip_runtime_markers("测试[mood:5]内容") == "测试内容"

    def test_multiple_markers_stripped(self):
        assert strip_runtime_markers("[happy]你好[affinity:50][sad]世界") == "你好世界"

    def test_no_markers_preserved(self):
        assert strip_runtime_markers("普通文本不变") == "普通文本不变"

    def test_whitespace_collapsed(self):
        result = strip_runtime_markers("[happy]  你好  [sad]  世界  ")
        assert "  " not in result
        assert "你好" in result
        assert "世界" in result
