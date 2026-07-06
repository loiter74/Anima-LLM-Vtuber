from __future__ import annotations

"""Tests for stateless subtitle translation helper.

Covers the behavioral contracts from design.md Decision 3 and spec requirements:
- Subtitle translation uses response_text as input, not a second authored answer.
- Prefers chat_messages() and does not call history-mutating chat() when available.
- Fallback translation restores LLM history or skips when safety cannot be guaranteed.
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
    """Fake LLM where chat_messages() delegates to chat() (default behavior).
    Has get_history/set_system_prompt for restoration."""

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


# ── Task 1.2: Prefers chat_messages(), does not call chat() ──


class TestPrefersChatMessages:
    """Prove translation uses chat_messages() and does not call
    history-mutating chat() when a native message-based path is available."""

    @pytest.mark.asyncio
    async def test_native_chat_messages_used(self):
        """When LLM has native chat_messages(), it should be used."""
        llm = _NativeChatMessagesLLM(translation="You're lagging again, streamer")

        result = await translate_subtitle_text(
            llm, "主播你又卡了", "Chinese", "English"
        )

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


# ── Task 1.3: Fallback translation restores history or skips ──


class TestFallbackBehavior:
    """Prove fallback translation restores LLM history or skips when
    history safety cannot be guaranteed."""

    @pytest.mark.asyncio
    async def test_fallback_with_restorable_history(self):
        """When LLM has get_history/clear_history, history should be restored."""
        llm = _FallbackLLM(translation="lagging again")

        result = await translate_subtitle_text(
            llm, "主播你又卡了", "Chinese", "English"
        )

        assert result == "lagging again"
        # History should have been restored (clear_history called)
        llm.clear_history.assert_called()

    @pytest.mark.asyncio
    async def test_unsafe_llm_skips_translation(self):
        """When LLM lacks history safety, translation should be skipped."""
        llm = _UnsafeLLM()

        result = await translate_subtitle_text(
            llm, "主播你又卡了", "Chinese", "English"
        )

        assert result is None
        # chat() should NOT have been called
        llm._chat_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_returns_none_on_empty_result(self):
        """When translation returns empty, return None."""
        llm = _FallbackLLM(translation="")
        llm._chat_mock = AsyncMock(return_value="")

        result = await translate_subtitle_text(
            llm, "测试", "Chinese", "English"
        )

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
