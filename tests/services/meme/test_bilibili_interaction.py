from __future__ import annotations

"""Tests for BilibiliInteractionLearner — danmaku processing, pattern analysis."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.services.bilibili import (
    DanmakuMessage,
    InteractionLearner,
    InteractionPattern,
    LivestreamStrategy,
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.chat_messages = AsyncMock()
    return llm


@pytest.fixture
def mock_wiki():
    wiki = MagicMock()
    wiki.write_page = MagicMock()
    return wiki


class TestDanmakuDataclasses:
    """DanmakuMessage, InteractionPattern, LivestreamStrategy dataclasses."""

    def test_danmaku_sample_defaults(self):

        s = DanmakuMessage(text="你好")
        assert s.text == "你好"
        assert isinstance(s.timestamp, float)
        assert s.is_gift is False
        assert s.is_super_chat is False

    def test_danmaku_sample_to_dict(self):

        s = DanmakuMessage(text="hello", timestamp=100.0, is_gift=True)
        d = s.to_dict()
        assert d["text"] == "hello"
        assert d["is_gift"] is True

    def test_interaction_pattern(self):

        p = InteractionPattern(
            name="测试模式",
            description="描述",
            applicable_scenarios=["场景1"],
            confidence=0.8,
        )
        d = p.to_dict()
        assert d["name"] == "测试模式"
        assert d["confidence"] == 0.8

    def test_livestream_strategy(self):

        s = LivestreamStrategy(
            trigger_condition="当弹幕刷屏时",
            suggested_behavior="回应热门弹幕",
            expected_effect="增加互动",
            priority="high",
        )
        d = s.to_dict()
        assert d["trigger_condition"] == "当弹幕刷屏时"
        assert d["priority"] == "high"


class TestBilibiliInteractionLearner:
    """Suite for BilibiliInteractionLearner."""

    # ── learn_patterns ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_learn_patterns_no_room_ids(self, mock_llm, mock_wiki):
        """With no room IDs configured, returns empty list."""

        learner = InteractionLearner(
            llm_client=mock_llm,
            wiki_manager=mock_wiki,
            config={"room_ids": []},
        )
        result = await learner.learn_patterns()
        assert result == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "collection_result",
        [[], RuntimeError("collection failed")],
        ids=["insufficient-samples", "collection-error"],
    )
    async def test_learn_patterns_skips_unusable_collections(
        self,
        mock_llm,
        mock_wiki,
        collection_result,
    ):
        """Insufficient samples and collection failures both skip the room."""

        learner = InteractionLearner(
            llm_client=mock_llm,
            wiki_manager=mock_wiki,
            config={"room_ids": [123], "min_samples_per_room": 100, "request_delay": 0},
        )

        with patch.object(learner, "_collect_danmaku") as mock_collect:
            if isinstance(collection_result, Exception):
                mock_collect.side_effect = collection_result
            else:
                mock_collect.return_value = collection_result
            result = await learner.learn_patterns()
            assert result == []

    @pytest.mark.asyncio
    async def test_learn_patterns_analyzes_and_stores_sufficient_samples(self, mock_llm, mock_wiki):
        """Sufficient samples are analyzed once and stored once."""

        mock_llm.chat_messages.return_value = {
            "content": (
                '{"patterns": [], "strategies": ['
                '{"trigger_condition": "弹幕多", "suggested_behavior": "回应", '
                '"expected_effect": "互动提升", "priority": "high"}], "summary": ""}'
            )
        }

        learner = InteractionLearner(
            llm_client=mock_llm,
            wiki_manager=mock_wiki,
            config={"room_ids": [123], "min_samples_per_room": 5, "request_delay": 0},
        )

        with patch.object(learner, "_collect_danmaku") as mock_collect:
            mock_collect.return_value = [DanmakuMessage(text=f"sample{i}") for i in range(10)]
            result = await learner.learn_patterns()
            assert len(result) == 1
            assert result[0].trigger_condition == "弹幕多"
            assert result[0].priority == "high"
            mock_wiki.write_page.assert_called_once()

    # ── _collect_danmaku ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_collect_danmaku_maps_shared_api_texts(self, mock_llm):
        """The learner maps text returned by the shared Bilibili API."""

        learner = InteractionLearner(llm_client=mock_llm)

        with patch(
            "animetta.services.bilibili.interaction_learner.api.fetch_live_danmaku",
            new=AsyncMock(return_value=["first", "second"]),
        ) as fetch:
            samples = await learner._collect_danmaku(room_id=123)

        assert [sample.text for sample in samples] == ["first", "second"]
        fetch.assert_awaited_once_with(123, limit=100)

    # ── _analyze_patterns ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_analyze_patterns_without_llm(self, mock_wiki):
        """Without LLM client, analysis returns empty list."""

        learner = InteractionLearner(
            llm_client=None,
            wiki_manager=mock_wiki,
        )
        result = await learner._analyze_patterns({123: []})
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_patterns_with_llm(self, mock_llm):
        """LLM analysis results should be parsed into LivestreamStrategy list."""

        mock_llm.chat_messages.return_value = {
            "content": (
                '{"patterns": [], "strategies": ['
                '{"trigger_condition": "A", "suggested_behavior": "B", '
                '"expected_effect": "C", "priority": "high"}], "summary": ""}'
            )
        }

        learner = InteractionLearner(llm_client=mock_llm)
        samples = [DanmakuMessage(text="测试" + str(i)) for i in range(5)]
        result = await learner._analyze_patterns({123: samples})
        assert len(result) == 1
        assert result[0].trigger_condition == "A"

    @pytest.mark.asyncio
    async def test_analyze_patterns_llm_error_fallback(self, mock_llm):
        """LLM exception returns empty list."""

        mock_llm.chat_messages.side_effect = RuntimeError("LLM error")
        learner = InteractionLearner(llm_client=mock_llm)
        result = await learner._analyze_patterns({123: []})
        assert result == []

    # ── _store_strategies ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_store_strategies_without_wiki(self, mock_llm):
        """No wiki manager: store is a no-op."""

        learner = InteractionLearner(llm_client=mock_llm, wiki_manager=None)
        strategies = [
            LivestreamStrategy(
                trigger_condition="测试",
                suggested_behavior="行为",
                expected_effect="效果",
                priority="low",
            ),
        ]
        await learner._store_strategies(strategies)  # no crash

    @pytest.mark.asyncio
    async def test_store_strategies_with_wiki(self, mock_llm, mock_wiki):
        """Store calls wiki.write_page with a WikiPage."""

        learner = InteractionLearner(
            llm_client=mock_llm,
            wiki_manager=mock_wiki,
        )
        strategies = [
            LivestreamStrategy(
                trigger_condition="冷场",
                suggested_behavior="互动",
                expected_effect="回暖",
                priority="high",
            ),
        ]
        await learner._store_strategies(strategies)
        mock_wiki.write_page.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_strategies_handles_exception(self, mock_llm, mock_wiki):
        """Exception during write should not propagate."""

        mock_wiki.write_page.side_effect = Exception("write failed")
        learner = InteractionLearner(
            llm_client=mock_llm,
            wiki_manager=mock_wiki,
        )
        strategies = [
            LivestreamStrategy(
                trigger_condition="X",
                suggested_behavior="Y",
                expected_effect="Z",
                priority="low",
            ),
        ]
        await learner._store_strategies(strategies)  # should not raise

    # ── _parse_json ──────────────────────────────────────────────────

    def test_parse_json(self):

        assert InteractionLearner._parse_json('{"a": 1}') == {"a": 1}

    def test_parse_json_with_fence(self):

        assert InteractionLearner._parse_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_parse_json_invalid(self):

        assert InteractionLearner._parse_json("{{{") == {}
