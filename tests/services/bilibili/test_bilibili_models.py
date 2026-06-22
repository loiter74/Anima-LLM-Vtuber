"""Tests for bilibili data models and text utilities."""

from __future__ import annotations

from animetta.services.bilibili.models import (
    CollectedComment,
    CollectedDanmaku,
    CollectedVideo,
    DanmakuMessage,
    DanmakuReply,
    InteractionPattern,
    LivestreamStrategy,
    MemeCandidate,
)
from animetta.services.bilibili.text_utils import extract_title_phrases, parse_tags


class TestDanmakuMessage:
    def test_create_basic(self):
        msg = DanmakuMessage(text="hello")
        assert msg.text == "hello"
        assert msg.is_gift is False
        assert msg.is_super_chat is False

    def test_to_dict(self):
        msg = DanmakuMessage(text="test", user_name="alice")
        d = msg.to_dict()
        assert d["text"] == "test"
        assert d["user_name"] == "alice"


class TestCollectedVideo:
    def test_create(self):
        v = CollectedVideo(bvid="BV123", title="Test Video")
        assert v.bvid == "BV123"
        assert v.tags == []

    def test_to_dict(self):
        v = CollectedVideo(bvid="BV123", title="T", tags=["a", "b"])
        d = v.to_dict()
        assert d["tags"] == ["a", "b"]


class TestCollectedComment:
    def test_create(self):
        c = CollectedComment(content="nice video")
        assert c.content == "nice video"
        assert c.likes == 0

    def test_to_dict(self):
        c = CollectedComment(content="x", likes=5)
        d = c.to_dict()
        assert d["likes"] == 5


class TestCollectedDanmaku:
    def test_create(self):
        d = CollectedDanmaku(content="danmaku text")
        assert d.content == "danmaku text"
        assert d.is_meme is False

    def test_to_dict_roundtrip(self):
        d = CollectedDanmaku(content="test", source_video="BV1")
        result = d.to_dict()
        assert result["source_video"] == "BV1"


class TestMemeCandidate:
    def test_create(self):
        m = MemeCandidate(text="new meme")
        assert m.text == "new meme"
        assert m.frequency == 1

    def test_to_dict(self):
        m = MemeCandidate(text="meme", source_videos=["BV1", "BV2"])
        d = m.to_dict()
        assert len(d["source_videos"]) == 2


class TestDanmakuReply:
    def test_create(self):
        r = DanmakuReply(danmaku_text="hi", reply_text="hello!", user_name="bob")
        assert r.reply_text == "hello!"
        assert r.character_name == "AI"


class TestInteractionPattern:
    def test_create(self):
        p = InteractionPattern(name="greeting", description="say hi")
        assert p.confidence == 0.5


class TestLivestreamStrategy:
    def test_create(self):
        s = LivestreamStrategy(
            trigger_condition="viewer count drops",
            suggested_behavior="tell a joke",
            expected_effect="engagement up",
        )
        assert s.priority == "medium"


# ── text_utils tests ──────────────────────────────────────────────


class TestParseTags:
    def test_basic(self):
        assert parse_tags("a,b,c") == ["a", "b", "c"]

    def test_empty(self):
        assert parse_tags("") == []

    def test_whitespace(self):
        assert parse_tags(" a , b ") == ["a", "b"]

    def test_none_like(self):
        assert parse_tags(None) == []


class TestExtractTitlePhrases:
    def test_basic(self):
        phrases = extract_title_phrases("这是测试！真的很好玩")
        assert len(phrases) > 0
        assert any("测试" in p for p in phrases)

    def test_empty(self):
        assert extract_title_phrases("") == []

    def test_short_title(self):
        phrases = extract_title_phrases("你好")
        assert "你好" in phrases
