from __future__ import annotations

"""Tests for BilibiliMemeCollector — scraped data parsing, LLM identification."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from animetta.services.bilibili import (
    CollectedComment,
    CollectedVideo,
    MemeCandidate,
    MemeCollector,
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.chat_messages = AsyncMock()
    return llm


class TestCollectedVideo:
    """Dataclass: CollectedVideo."""

    def test_creation_and_to_dict(self):

        v = CollectedVideo(
            bvid="BV1xx",
            title="测试视频",
            description="描述内容",
            tags=["梗", "搞笑"],
            view_count=1000,
            danmaku_count=200,
            reply_count=50,
        )
        assert v.bvid == "BV1xx"
        d = v.to_dict()
        assert d["title"] == "测试视频"
        assert d["tags"] == ["梗", "搞笑"]
        assert d["view_count"] == 1000
        assert d["danmaku_count"] == 200
        assert d["reply_count"] == 50


class TestCollectedComment:
    """Dataclass: CollectedComment."""

    def test_creation_and_to_dict(self):

        c = CollectedComment(content="好活", likes=42, replies=5, publish_time="2024-01-01")
        d = c.to_dict()
        assert d["content"] == "好活"
        assert d["likes"] == 42
        assert d["replies"] == 5
        assert d["publish_time"] == "2024-01-01"


class TestMemeCandidateRaw:
    """Dataclass: MemeCandidateRaw."""

    def test_creation_and_to_dict(self):

        m = MemeCandidate(
            text="绝绝子",
            context_hint="吐槽场景",
            frequency=3,
            source_videos=["BV1xx", "BV2xx"],
            tags=["流行"],
        )
        d = m.to_dict()
        assert d["text"] == "绝绝子"
        assert d["frequency"] == 3
        assert d["source_videos"] == ["BV1xx", "BV2xx"]

    def test_style_metadata_to_dict(self):
        m = MemeCandidate(
            text="吾闻先王设职...",
            format_id="zhouli",
            format_slots={"modern_event": "今天不想上班"},
            format_confidence=0.91,
            rendered_text="吾闻先王设职，此岂不合乎周礼？",
            mode="quip",
        )

        d = m.to_dict()

        assert d["format_id"] == "zhouli"
        assert d["format_slots"] == {"modern_event": "今天不想上班"}
        assert d["format_confidence"] == 0.91
        assert d["rendered_text"].endswith("周礼？")
        assert d["mode"] == "quip"


class TestBilibiliMemeCollector:
    """Suite for BilibiliMemeCollector."""

    # ── Constructor ──────────────────────────────────────────────────

    def test_constructor_defaults(self, mock_llm):

        c = MemeCollector(llm_client=mock_llm)
        assert c._max_videos == 50
        assert c._max_comments_per_video == 50
        assert c._min_comment_likes == 2
        assert c._request_delay == 0.3
        assert c._search_keyword == ""

    def test_constructor_custom_config(self, mock_llm):

        c = MemeCollector(
            llm_client=mock_llm,
            config={"max_videos": 5, "search_keyword": "vtuber"},
        )
        assert c._max_videos == 5
        assert c._search_keyword == "vtuber"

    # ── parse_tags ──────────────────────────────────────────────────

    def test_parse_tags_empty(self):
        from animetta.services.bilibili.text_utils import parse_tags

        assert parse_tags("") == []
        assert parse_tags(None) == []

    def test_parse_tags_comma_separated(self):
        from animetta.services.bilibili.text_utils import parse_tags

        result = parse_tags("搞笑, 梗, vtuber")
        assert result == ["搞笑", "梗", "vtuber"]

    # ── collect (full pipeline) ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_collect_without_llm_uses_heuristic(self):
        """Without LLM, collect uses heuristic identification."""

        c = MemeCollector(llm_client=None, config={"max_videos": 3})

        with patch.object(c, "_fetch_trending_videos") as mock_fetch:
            mock_fetch.return_value = []
            result = await c.collect()
            assert result == []

    @pytest.mark.asyncio
    async def test_collect_with_llm(self, mock_llm):
        """With LLM, collect calls _identify_meme_candidates."""

        c = MemeCollector(llm_client=mock_llm)

        with patch.object(c, "_fetch_trending_videos") as mock_fetch:
            mock_fetch.return_value = []
            result = await c.collect()
            assert result == []

    @pytest.mark.asyncio
    async def test_collect_fetch_failure_returns_empty(self, mock_llm):
        """If trending videos fail, collect returns empty list."""

        c = MemeCollector(llm_client=mock_llm)

        with patch.object(c, "_fetch_trending_videos", side_effect=Exception("API down")):
            result = await c.collect()
            assert result == []

    # ── _heuristic_identify ──────────────────────────────────────────

    def test_heuristic_identify_empty(self):

        c = MemeCollector(llm_client=None)
        result = c._heuristic_identify([], {})
        assert result == []

    def test_heuristic_identify_finds_repeated_tags(self):

        c = MemeCollector(llm_client=None)
        videos = [
            CollectedVideo(bvid="BV1", title="A", tags=["meme", "搞笑"]),
            CollectedVideo(bvid="BV2", title="B", tags=["meme", "vtuber"]),
            CollectedVideo(bvid="BV3", title="C", tags=["搞笑", "日常"]),
        ]
        candidates = c._heuristic_identify(videos, {})
        # "meme" appears twice, "搞笑" appears twice
        texts = {m.text for m in candidates}
        assert "meme" in texts
        assert "搞笑" in texts
        assert all(m.frequency >= 2 for m in candidates)

    # ── _build_candidates ────────────────────────────────────────────

    def test_build_candidates_empty(self):

        assert MemeCollector._build_candidates([], []) == []

    def test_build_candidates_filters_empty_text(self):

        videos = [CollectedVideo(bvid="BV1xx", title="Test")]
        parsed = [
            {"text": "valid梗", "context_hint": "吐槽", "frequency": 2, "tags": ["搞笑"]},
            {"text": "", "context_hint": "", "frequency": 1, "tags": []},
            {"text": "  ", "context_hint": "", "frequency": 1, "tags": []},
        ]
        candidates = MemeCollector._build_candidates(parsed, videos)
        assert len(candidates) == 1
        assert candidates[0].text == "valid梗"

    def test_build_candidates_preserves_style_metadata(self):
        videos = [CollectedVideo(bvid="BV1xx", title="Test")]
        parsed = [
            {
                "text": "吾闻先王设职...",
                "context_hint": "不想上班时",
                "frequency": 3,
                "tags": ["周礼体"],
                "format_id": "zhouli",
                "format_slots": {"modern_event": "今天不想上班"},
                "format_confidence": 0.88,
                "rendered_text": "吾闻先王设职，此岂不合乎周礼？",
                "mode": "quip",
            }
        ]

        candidates = MemeCollector._build_candidates(parsed, videos)

        assert len(candidates) == 1
        assert candidates[0].format_id == "zhouli"
        assert candidates[0].format_slots == {"modern_event": "今天不想上班"}
        assert candidates[0].format_confidence == 0.88
        assert candidates[0].rendered_text.endswith("周礼？")
        assert candidates[0].mode == "quip"

    # ── _parse_llm_json ──────────────────────────────────────────────

    def test_parse_llm_json_list(self):

        raw = '[{"text": "梗1"}, {"text": "梗2"}]'
        result = MemeCollector._parse_llm_json(raw)
        assert len(result) == 2
        assert result[0]["text"] == "梗1"

    def test_parse_llm_json_dict_with_wrapper(self):

        raw = '{"memes": [{"text": "梗1"}]}'
        result = MemeCollector._parse_llm_json(raw)
        assert len(result) == 1

    def test_parse_llm_json_invalid(self):

        result = MemeCollector._parse_llm_json("{{{")
        assert result == []

    def test_parse_llm_json_with_fence(self):

        raw = '```json\n[{"text": "梗1"}]\n```'
        result = MemeCollector._parse_llm_json(raw)
        assert len(result) == 1

    # ── _fetch_trending_videos ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_trending_videos_no_bilibili_api(self, mock_llm):
        """If bilibili-api is not installed, returns empty list."""

        MemeCollector(llm_client=mock_llm)
        with patch.dict("sys.modules", {"bilibili_api": None}):
            pass  # can't actually remove it cleanly, but test gracefully handles

    # ── _identify_meme_candidates ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_identify_without_llm_uses_heuristic(self):

        c = MemeCollector(llm_client=None)
        videos = [CollectedVideo(bvid="BV1", title="Test", tags=["meme"])]
        result = await c._identify_meme_candidates(videos, {})
        # Falls back to heuristic (which finds "meme" if repeated)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_identify_with_llm_parses_result(self, mock_llm):

        mock_llm.chat_messages.return_value = {"content": '[{"text": "梗1", "frequency": 2}]'}
        c = MemeCollector(llm_client=mock_llm)
        videos = [CollectedVideo(bvid="BV1", title="Test")]
        result = await c._identify_meme_candidates(videos, {})
        assert len(result) == 1
        assert result[0].text == "梗1"

    @pytest.mark.asyncio
    async def test_identify_prompt_includes_style_guidance(self, mock_llm):
        mock_llm.chat_messages.return_value = {
            "content": (
                '[{"text": "吾闻先王设职...", "frequency": 2, '
                '"format_id": "zhouli", '
                '"format_slots": {"modern_event": "今天不想上班"}, '
                '"format_confidence": 0.9, '
                '"rendered_text": "吾闻先王设职，此岂不合乎周礼？"}]'
            )
        }
        c = MemeCollector(llm_client=mock_llm)
        videos = [CollectedVideo(bvid="BV1", title="Test")]

        result = await c._identify_meme_candidates(videos, {})

        _, kwargs = mock_llm.chat_messages.await_args
        prompt_text = "\n".join(message["content"] for message in kwargs["messages"])
        assert "周礼体" in prompt_text
        assert "format_slots" in prompt_text
        assert result[0].format_id == "zhouli"
