from __future__ import annotations

"""Tests for LLM reasoning node — tool-calling and streaming paths."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.types import RunnableConfig

from animetta.orchestration.graph import llm_node
from animetta.orchestration.graph.llm_node import (
    FALLBACK_RESPONSE,
    _enforce_persona_verbal_tics,
)
from animetta.orchestration.graph.state import create_initial_state


def _make_config(service_context=None, enable_tools=False, chat_model=None):
    """Helper to build a RunnableConfig with test overrides."""
    configurable = {}
    if service_context:
        configurable["service_context"] = service_context
    if enable_tools:
        configurable["enable_tools"] = True
    if chat_model:
        configurable["chat_model"] = chat_model
    # Prevent MemoryMiddleware auto-creation from mock memory_system
    configurable["memory_middleware"] = None
    return RunnableConfig(configurable=configurable)


# ── Empty / error inputs ──────────────────────────────────────────


class TestLLMNodeErrors:
    """Edge cases and invalid inputs."""

    @pytest.mark.asyncio
    async def test_empty_user_text_returns_error(self):
        """Empty user_text should immediately return an error without calling LLM."""

        state = create_initial_state(
            session_id="test-session",
            user_text="",
        )
        result = await llm_node(state)
        assert result.get("error") is not None
        assert "No user text" in result.get("error", "") or "无用户文本" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_no_service_context_returns_error(self):
        """Missing service_context in config returns error."""

        state = create_initial_state(
            session_id="test-session",
            user_text="你好",
        )
        # Config without service_context
        config = RunnableConfig(configurable={})
        result = await llm_node(state, config)
        assert result.get("error") is not None
        assert "service_context" in result["error"]

    @pytest.mark.asyncio
    async def test_no_llm_engine_returns_error(self, mock_service_context):
        """Service context without llm_engine returns error."""

        ctx = MagicMock()
        ctx.llm_engine = None
        ctx.core.config = None

        state = create_initial_state(
            session_id="test-session",
            user_text="你好",
        )
        config = _make_config(service_context=ctx)
        result = await llm_node(state, config)
        assert result.get("error") is not None
        assert "not initialized" in result["error"].lower() or "LLM" in result.get("error", "")


# ── Streaming path (no tools) ─────────────────────────────────────


class TestLLMNodeWithoutTools:
    """Normal streaming response, no tool calling."""

    @pytest.mark.asyncio
    async def test_streaming_returns_response_text(self, mock_service_context):
        """llm_node returns response_text from streaming LLM."""

        async def _chat_stream(user_text, system_prompt=""):
            yield "Hello"
            yield " world"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="Hi there",
            system_prompt="You are a helpful assistant.",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result.get("response_text") == "Hello world"
        assert result["response_chunks"] == ["Hello", " world"]
        assert result["tool_calls"] is None

    @pytest.mark.asyncio
    async def test_streaming_empty_response(self, mock_service_context):
        """Empty stream should result in empty response_text."""

        async def _chat_stream(user_text, system_prompt=""):
            if False:
                yield
            return

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="hello",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result.get("response_text") == ""
        assert result["response_chunks"] == []
        assert result["messages"] is not None

    @pytest.mark.asyncio
    async def test_streaming_injects_system_prompt(self, mock_service_context):
        """System prompt from state should be passed to LLM."""

        captured_system_prompt = None

        async def _chat_stream(user_text, system_prompt=""):
            nonlocal captured_system_prompt
            captured_system_prompt = system_prompt
            yield "response"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="hello",
            system_prompt="Be funny",
        )
        config = _make_config(service_context=mock_service_context)
        await llm_node(state, config)

        # Verify system_prompt was passed to the LLM
        assert captured_system_prompt is not None
        assert "Be funny" in captured_system_prompt

    @pytest.mark.asyncio
    async def test_streaming_enforces_explicit_nya_suffix(self, mock_service_context):
        """When persona prompt requires 喵 suffixes, visible response should keep them."""

        async def _chat_stream(user_text, system_prompt=""):
            yield "不是我卡了，是后厨又进虫子了。旅人稍等一下。"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="主播你又卡了",
            system_prompt="你扮演猫娘，与我对话时每一句话后面都要加上喵。",
        )
        config = _make_config(service_context=mock_service_context)
        result = await llm_node(state, config)

        assert result["response_text"] == "不是我卡了，是后厨又进虫子了喵。旅人稍等一下喵。"


# ── Tool-calling path ─────────────────────────────────────────────


class TestLLMNodeWithTools:
    """Tool-augmented LLM responses."""

    @pytest.mark.asyncio
    async def test_tool_call_returns_tool_calls(self, mock_service_context):
        """When LLM returns tool_calls, they should be in the result."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [
            MagicMock(name="web_search", description="Search the web"),
            MagicMock(name="calculator", description="Do math"),
        ]

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "Let me search for that",
                "tool_calls": [
                    {"id": "call_1", "name": "web_search", "args": {"query": "weather"}},
                ],
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["tool_calls"] is not None
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["name"] == "web_search"
        assert result["tool_calls"][0]["args"]["query"] == "weather"

    @pytest.mark.asyncio
    async def test_tool_call_without_tools_returns_text(self, mock_service_context):
        """When LLM returns content without tool_calls, response_text is set."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "The weather is sunny today!",
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["tool_calls"] is None
        assert result["response_text"] == "The weather is sunny today!"

    @pytest.mark.asyncio
    async def test_tool_text_enforces_explicit_nya_suffix(self, mock_service_context):
        """Tool-calling text path should apply the same visible persona guard."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = []

        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            return_value={
                "content": "不是我卡了，是后厨又进虫子了。旅人稍等一下。",
            }
        )

        state = create_initial_state(
            session_id="test-session",
            user_text="主播你又卡了",
            system_prompt="你扮演猫娘，与我对话时每一句话后面都要加上喵。",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        result = await llm_node(state, config)

        assert result["response_text"] == "不是我卡了，是后厨又进虫子了喵。旅人稍等一下喵。"

    @pytest.mark.asyncio
    async def test_tool_call_error_falls_back_to_streaming(self, mock_service_context):
        """When chat_with_tools raises, it should fall back to streaming path."""

        mock_chat_model = MagicMock()
        mock_chat_model.bound_tools = [MagicMock(name="web_search")]

        # Tool path raises
        mock_service_context.llm_engine.chat_with_tools = AsyncMock(
            side_effect=Exception("API error")
        )

        # Streaming path works
        async def _chat_stream(user_text, system_prompt=""):
            yield "Fallback response"

        mock_service_context.llm_engine.chat_stream = _chat_stream

        state = create_initial_state(
            session_id="test-session",
            user_text="What is the weather?",
        )
        config = _make_config(
            service_context=mock_service_context,
            enable_tools=True,
            chat_model=mock_chat_model,
        )
        # Should not raise — falls back to streaming
        result = await llm_node(state, config)

        assert result["tool_calls"] is None
        assert result["response_text"] == "Fallback response"


# ── Timeout / Error Resilience ────────────────────────────────────


class TestLLMTimeout:
    """LLM timeout triggers fallback response with error metadata."""

    @pytest.mark.asyncio
    async def test_llm_timeout_triggers_fallback(self, mock_service_context):
        """When LLM streaming times out, fallback text is returned, no exception propagates."""

        async def _chat_stream_hangs(user_text, system_prompt=""):
            await asyncio.sleep(999)
            yield "never"

        mock_service_context.llm_engine.chat_stream = _chat_stream_hangs

        state = create_initial_state(
            session_id="test-timeout",
            user_text="Hello",
        )
        config = _make_config(service_context=mock_service_context)
        config["configurable"]["llm_timeout"] = 0.001

        result = await llm_node(state, config)

        assert result["response_text"] == FALLBACK_RESPONSE
        assert result["response_chunks"] == [FALLBACK_RESPONSE]
        assert result["tool_calls"] is None
        assert result.get("metadata", {}).get("error_type") == "timeout"

    @pytest.mark.asyncio
    async def test_fallback_is_per_turn(self, mock_service_context):
        """After timeout on turn N, turn N+1 attempts real provider again."""

        # Turn 1: force timeout → fallback
        async def _chat_stream_timeout(user_text, system_prompt=""):
            await asyncio.sleep(999)
            yield "never"

        mock_service_context.llm_engine.chat_stream = _chat_stream_timeout

        state1 = create_initial_state(
            session_id="test-per-turn",
            user_text="hi",
        )
        config1 = _make_config(service_context=mock_service_context)
        config1["configurable"]["llm_timeout"] = 0.001

        result1 = await llm_node(state1, config1)
        assert result1.get("metadata", {}).get("error_type") == "timeout"

        # Turn 2: real provider works normally
        async def _chat_stream_real(user_text, system_prompt=""):
            yield "real response"

        mock_service_context.llm_engine.chat_stream = _chat_stream_real

        state2 = create_initial_state(
            session_id="test-per-turn",
            user_text="hello again",
        )
        config2 = _make_config(service_context=mock_service_context)
        config2["configurable"]["llm_timeout"] = 30

        result2 = await llm_node(state2, config2)
        assert result2["response_text"] == "real response"
        assert "error_type" not in result2.get("metadata", {})


# ── Affinity marker parsing ────────────────────────────────────────


class TestAffinityMarkerParsing:
    """Tests for the [affinity:N] marker parser in llm_node.

    The LLM emits this marker at the end of each reply (per the
    AffinityPromptSource contract). The parser must:
    - extract the value into state["affinity"] + metadata
    - strip the marker from user-visible text
    - leave previous affinity untouched when no marker is present
    - clamp out-of-range values
    """

    def test_marker_parsed_and_stripped(self):
        """A valid [affinity:N] marker is parsed and removed from text."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        cleaned = _extract_and_update_affinity(state, "老朋友来了 [affinity:82]")
        assert state["affinity"] == 82
        assert state["metadata"]["affinity"] == 82
        assert "[affinity:" not in cleaned
        assert "老朋友来了" in cleaned


class TestPersonaVerbalTicEnforcement:
    """Narrow response post-processing for explicit persona verbal tics."""

    def test_noop_without_explicit_nya_rule(self):
        text = "不是我卡了，是后厨又进虫子了。"
        prompt = "你是 Anima。"
        assert _enforce_persona_verbal_tics(text, prompt) == text

    def test_adds_nya_before_chinese_sentence_punctuation(self):
        prompt = "你扮演猫娘，与我对话时每一句话后面都要加上喵。"
        text = "不是我卡了，是后厨又进虫子了。旅人稍等一下！"
        assert (
            _enforce_persona_verbal_tics(text, prompt)
            == "不是我卡了，是后厨又进虫子了喵。旅人稍等一下喵！"
        )

    def test_does_not_duplicate_existing_nya(self):
        prompt = "你扮演猫娘，与我对话时每一句话后面都要加上喵。"
        text = "已经有了喵。下一句没有。"
        assert _enforce_persona_verbal_tics(text, prompt) == "已经有了喵。下一句没有喵。"

    def test_no_marker_keeps_previous_affinity(self):
        """When no marker is present, the prior affinity value carries over."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"affinity": 50, "metadata": {"affinity": 50}}
        cleaned = _extract_and_update_affinity(state, "Just a normal reply.")
        # Value untouched
        assert state["affinity"] == 50
        assert state["metadata"]["affinity"] == 50
        # Text unchanged
        assert cleaned == "Just a normal reply."

    def test_high_value_clamped_to_max(self):
        """Out-of-range high values are clamped to AFFINITY_MAX (100)."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        _extract_and_update_affinity(state, "[affinity:500]")
        assert state["affinity"] == 100

    def test_negative_value_clamped_to_min(self):
        """Negative values are clamped to AFFINITY_MIN (0)."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        _extract_and_update_affinity(state, "[affinity:-30]")
        assert state["affinity"] == 0

    def test_multiple_markers_last_wins(self):
        """When multiple markers appear, the last one is canonical."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        _extract_and_update_affinity(state, "First [affinity:30] then [affinity:60]")
        assert state["affinity"] == 60

    def test_marker_anywhere_in_text(self):
        """Marker can appear at start, middle, or end of the response."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        for text in [
            "[affinity:55] Hello",
            "Hello [affinity:55] world",
            "Hello world [affinity:55]",
        ]:
            state = {"metadata": {}}
            cleaned = _extract_and_update_affinity(state, text)
            assert state["affinity"] == 55
            assert "[affinity:" not in cleaned

    def test_empty_response_no_crash(self):
        """Empty/None response does not crash; returns empty/unchanged."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"metadata": {}}
        # Empty string
        cleaned = _extract_and_update_affinity(state, "")
        assert cleaned == ""
        # None
        cleaned_none = _extract_and_update_affinity(state, None)
        assert cleaned_none is None or cleaned_none == ""

    def test_debug_turn_keeps_marker_visible(self):
        """When user_text contains 【debug】, the marker is preserved.

        This is the visibility switch: the value is still parsed and written
        to state, but the marker stays in the returned text so the user can
        see the raw number.
        """
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"user_text": "【debug】显示好感度", "metadata": {}}
        cleaned = _extract_and_update_affinity(state, "你对我有 65 分。[affinity:65]")
        # State still updated
        assert state["affinity"] == 65
        assert state["metadata"]["affinity"] == 65
        # Marker kept visible
        assert "[affinity:65]" in cleaned

    def test_normal_turn_strips_marker(self):
        """Without 【debug】, the marker is stripped from visible text."""
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        state = {"user_text": "你好啊", "metadata": {}}
        cleaned = _extract_and_update_affinity(state, "你好。[affinity:55]")
        assert state["affinity"] == 55
        assert "[affinity:" not in cleaned

    def test_debug_detection_case_sensitive(self):
        """【debug】 is matched as-is (full-width brackets, lowercase).

        Half-width [debug] or upper 【DEBUG】 should NOT trigger the switch —
        we follow the exact contract from the persona spec.
        """
        from animetta.orchestration.graph.llm_node import _extract_and_update_affinity

        # Half-width [debug] → stripped (not a debug turn)
        state1 = {"user_text": "[debug] show me", "metadata": {}}
        cleaned1 = _extract_and_update_affinity(state1, "hi [affinity:50]")
        assert "[affinity:" not in cleaned1, "half-width [debug] should NOT keep marker"

        # Full-width 【DEBUG】 (uppercase) → stripped (case-sensitive)
        state2 = {"user_text": "【DEBUG】", "metadata": {}}
        cleaned2 = _extract_and_update_affinity(state2, "hi [affinity:50]")
        assert "[affinity:" not in cleaned2, "【DEBUG】 uppercase should NOT keep marker"

        # Exact 【debug】 → kept
        state3 = {"user_text": "【debug】", "metadata": {}}
        cleaned3 = _extract_and_update_affinity(state3, "hi [affinity:50]")
        assert "[affinity:50]" in cleaned3, "exact 【debug】 should keep marker"


class TestEmotionRegexAndAffinityMarker:
    """Responsibility split between _strip_emotion_tags and affinity parser.

    Design decision: ``_strip_emotion_tags`` does NOT touch ``[affinity:N]``
    markers. Affinity stripping is the exclusive job of
    ``_extract_and_update_affinity``, which respects the 【debug】 visibility
    switch. If the emotion stripper also stripped affinity markers, it would
    clobber a marker the affinity parser deliberately preserved on a debug
    turn.
    """

    def test_strip_emotion_tags_leaves_affinity_marker_alone(self):
        """_strip_emotion_tags does NOT strip [affinity:67].

        Regression guard for the 【debug】 visibility contract: when the user
        asks for debug, the affinity parser keeps the marker; the emotion
        stripper must not undo that.
        """
        from animetta.orchestration.graph.llm_node import _strip_emotion_tags

        # Affinity marker survives the emotion stripper
        result = _strip_emotion_tags("Reply [affinity:67]")
        assert "[affinity:67]" in result, "emotion regex must not touch affinity marker"
        assert "Reply" in result

    def test_strip_emotion_tags_strips_emotion_tags(self):
        """_strip_emotion_tags still strips [happy], [neutral], etc."""
        from animetta.orchestration.graph.llm_node import _strip_emotion_tags

        assert _strip_emotion_tags("Reply [happy]") == "Reply"
        assert _strip_emotion_tags("[neutral] hi") == "hi"

    def test_strip_emotion_tags_preserves_plain_text(self):
        """Text without any bracket tags is returned unchanged (modulo whitespace)."""
        from animetta.orchestration.graph.llm_node import _strip_emotion_tags

        assert _strip_emotion_tags("普通的一句话。") == "普通的一句话。"

    def test_response_text_clean_on_normal_turn(self):
        """Normal turn: response_text has no [affinity:N] after full pipeline.

        _extract_and_update_affinity strips the marker (no 【debug】 in user_text),
        then _strip_emotion_tags runs but doesn't add it back.
        """
        from animetta.orchestration.graph.llm_node import (
            _extract_and_update_affinity,
            _strip_emotion_tags,
        )

        # No 【debug】 in user_text → marker stripped
        state = {"user_text": "今晚特调不错。", "metadata": {}}
        full = "今晚特调不错。[affinity:72]"
        cleaned = _extract_and_update_affinity(state, full)
        final = _strip_emotion_tags(cleaned)
        assert "[affinity:" not in final
        assert "今晚特调不错" in final

    def test_response_text_keeps_marker_on_debug_turn(self):
        """【debug】 turn: the affinity marker stays visible to the user.

        This is the visibility switch — _extract_and_update_affinity sees
        【debug】 in user_text and returns the text with marker intact.
        """
        from animetta.orchestration.graph.llm_node import (
            _extract_and_update_affinity,
            _strip_emotion_tags,
        )

        state = {"user_text": "【debug】让我看看好感度", "metadata": {}}
        full = "你对我是 65 分的好感。[affinity:65]"
        cleaned = _extract_and_update_affinity(state, full)
        final = _strip_emotion_tags(cleaned)
        # Marker must survive BOTH the affinity parser AND the emotion stripper
        assert "[affinity:65]" in final, (
            f"【debug】 turn must keep the marker visible; got: {final!r}"
        )
