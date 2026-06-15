from __future__ import annotations

"""Tests for MemeCognitiveAnalyzer — LLM-driven humor mechanism analysis."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from animetta.services.meme.analyzer import MemeCognitiveAnalyzer


@pytest.fixture
def mock_llm():
    """A mock LLM client with .chat_messages returning JSON content."""
    llm = MagicMock()
    llm.chat_messages = AsyncMock()
    return llm


@pytest.fixture
def mock_meme_pool():
    pool = MagicMock()
    pool.add_from_candidate = MagicMock()
    pool.store = MagicMock()
    pool.store.update = MagicMock()
    return pool


@pytest.fixture
def analyzer(mock_llm, mock_meme_pool):

    return MemeCognitiveAnalyzer(
        llm_client=mock_llm,
        meme_pool=mock_meme_pool,
        config={"min_persona_fit_score": 0.5},
    )


_MOCK_VALID_JSON = (
    '{"humor_mechanism": "双关", "context_trigger": "当用户抱怨时", '
    '"emotional_tone": "幽默", "persona_fit_score": 0.8,'
    '"usage_example": "这个梗真有意思"}'
)


class TestMemeCognitiveAnalyzer:
    """Suite for MemeCognitiveAnalyzer."""

    # ── analyze (with LLM) ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_analyze_returns_cognitive_analysis(self, analyzer, mock_llm):
        """Successful LLM call should return a CognitiveAnalysis."""
        mock_llm.chat_messages.return_value = {"content": _MOCK_VALID_JSON}
        result = await analyzer.analyze(text="测试梗", context_hint="吐槽场景")

        assert isinstance(result, dict)
        assert result.humor_mechanism == "双关"
        assert result.persona_fit_score == 0.8

    @pytest.mark.asyncio
    async def test_analyze_passes_correct_prompt(self, analyzer, mock_llm):
        """The LLM should receive system + user prompt with the meme text."""
        mock_llm.chat_messages.return_value = {"content": _MOCK_VALID_JSON}
        await analyzer.analyze(text="绝绝子", context_hint="网络用语", tags=["流行"])
        mock_llm.chat_messages.assert_awaited_once()
        _, kwargs = mock_llm.chat_messages.await_args
        messages = kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "梗" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert "绝绝子" in messages[1]["content"]

    @pytest.mark.asyncio
    async def test_analyze_handles_llm_error(self, analyzer, mock_llm):
        """LLM failure should fall back to basic analysis."""
        mock_llm.chat_messages.side_effect = RuntimeError("LLM down")
        result = await analyzer.analyze(text="测试", context_hint="吐槽")

        assert isinstance(result, dict)
        assert result.humor_mechanism == ""  # basic fallback
        assert result.persona_fit_score == 0.5

    @pytest.mark.asyncio
    async def test_analyze_invalid_json_uses_fallback(self, analyzer, mock_llm):
        """Invalid JSON from LLM should produce a basic analysis."""
        mock_llm.chat_messages.return_value = {"content": "not json at all"}
        result = await analyzer.analyze(text="测试")
        assert result.humor_mechanism == ""

    # ── analyze (without LLM — degraded mode) ────────────────────────

    @pytest.mark.asyncio
    async def test_analyze_no_llm_returns_basic(self, mock_meme_pool):
        """Without an LLM client, analyze returns basic analysis."""

        a = MemeCognitiveAnalyzer(llm_client=None, meme_pool=mock_meme_pool)
        result = await a.analyze(text="摆烂了", context_hint="摸鱼")
        assert result.persona_fit_score == 0.5
        assert result.humor_mechanism == ""

    # ── analyze_and_ingest ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_analyze_and_ingest_success(self, analyzer, mock_llm, mock_meme_pool):
        """High persona fit should ingest into MemePool."""
        mock_llm.chat_messages.return_value = {"content": _MOCK_VALID_JSON}

        mock_meme = MagicMock()
        mock_meme.id = "meme_123"
        mock_meme_pool.add_from_candidate.return_value = mock_meme

        result = await analyzer.analyze_and_ingest(text="测试梗")
        assert result is mock_meme
        mock_meme_pool.add_from_candidate.assert_called_once()
        mock_meme_pool.store.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyze_and_ingest_rejects_low_fit(self, analyzer, mock_llm, mock_meme_pool):
        """Low persona fit score should reject the meme (return None)."""
        low_fit_json = (
            '{"humor_mechanism": "双关", "context_trigger": "测试", '
            '"emotional_tone": "一般", "persona_fit_score": 0.3,'
            '"usage_example": "不怎么好笑"}'
        )
        mock_llm.chat_messages.return_value = {"content": low_fit_json}
        result = await analyzer.analyze_and_ingest(text="无聊梗")
        assert result is None
        mock_meme_pool.add_from_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_and_ingest_analysis_failure(self, analyzer, mock_llm, mock_meme_pool):
        """When analysis fails, should create a bare meme with confidence=0.5."""
        mock_llm.chat_messages.side_effect = RuntimeError("fail")
        mock_meme_pool.add_from_candidate.return_value = MagicMock(id="bare_meme")

        result = await analyzer.analyze_and_ingest(text="fallback梗")
        assert result is not None
        mock_meme_pool.add_from_candidate.assert_called_once()
        args, kwargs = mock_meme_pool.add_from_candidate.call_args
        assert kwargs.get("confidence") == 0.5

    # ── _parse_json ──────────────────────────────────────────────────

    def test_parse_json_plain(self, analyzer):
        """Plain JSON string parses correctly."""
        assert analyzer._parse_json('{"a": 1}') == {"a": 1}

    def test_parse_json_with_markdown_fence(self, analyzer):
        """Markdown-fenced JSON should be stripped."""
        raw = "```json\n{\"a\": 1}\n```"
        assert analyzer._parse_json(raw) == {"a": 1}

    def test_parse_json_with_plain_fence(self, analyzer):
        """Plain ``` fence (no json tag) should also be stripped."""
        raw = "```\n{\"a\": 1}\n```"
        assert analyzer._parse_json(raw) == {"a": 1}

    def test_parse_json_invalid_returns_empty(self, analyzer):
        """Invalid input returns empty dict."""
        assert analyzer._parse_json("{{{") == {}

    # ── _validate_analysis ───────────────────────────────────────────

    def test_validate_analysis_valid(self, analyzer):
        data = {
            "humor_mechanism": "反讽",
            "context_trigger": "测试",
            "emotional_tone": "讽刺",
            "persona_fit_score": 0.7,
            "usage_example": "示例",
        }
        assert analyzer._validate_analysis(data) is True

    def test_validate_analysis_missing_field(self, analyzer):
        data = {"humor_mechanism": "反讽"}  # missing fields
        assert analyzer._validate_analysis(data) is False

    def test_validate_analysis_empty(self, analyzer):
        assert analyzer._validate_analysis({}) is False

    def test_validate_analysis_out_of_range_score(self, analyzer):
        data = {
            "humor_mechanism": "反讽",
            "context_trigger": "测试",
            "emotional_tone": "讽刺",
            "persona_fit_score": 1.5,  # > 1.0
            "usage_example": "示例",
        }
        assert analyzer._validate_analysis(data) is False

    def test_validate_analysis_none(self, analyzer):
        assert analyzer._validate_analysis(None) is False

    # ── _basic_analysis ──────────────────────────────────────────────

    def test_basic_analysis_defaults(self, analyzer):

        result = analyzer._basic_analysis(text="测试", context_hint="场景", source_url="url")
        assert isinstance(result, dict)
        assert result.humor_mechanism == ""
        assert result.context_trigger == "场景"
        assert result.persona_fit_score == 0.5
        assert result.source_url == "url"
