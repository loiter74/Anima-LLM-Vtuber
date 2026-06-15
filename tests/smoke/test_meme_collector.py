"""Smoke tests for the meme collector — module loading and data structures.

These tests verify that the meme module can be imported and its API surface
works correctly. They do NOT call Bilibili or LLM APIs.
"""



# ── Module imports ──────────────────────────────────────────────────


def test_meme_module_imports():
    """Core meme types should be importable."""
    from animetta.services.bilibili import DanmakuBuffer, DanmakuPhrase

    assert DanmakuBuffer is not None
    assert DanmakuPhrase is not None


def test_bilibili_collector_imports():
    """BilibiliMemeCollector and MemeCandidateRaw should be importable."""
    from animetta.services.bilibili import (
        MemeCandidate,
        MemeCollector,
    )

    assert MemeCollector is not None
    assert MemeCandidate is not None


def test_meme_analyzer_imports():
    """MemeCognitiveAnalyzer should be importable."""
    from animetta.services.meme.analyzer import MemeCognitiveAnalyzer

    assert MemeCognitiveAnalyzer is not None


# ── Data structures ─────────────────────────────────────────────────


def test_danmaku_phrase_fields():
    """DanmakuPhrase should have expected fields."""
    from animetta.services.bilibili import DanmakuPhrase

    phrase = DanmakuPhrase(
        text="草",
        frequency=5,
        first_seen=1234567.0,
        last_seen=1234667.0,
        source_room_id="12345",
    )
    assert phrase.text == "草"
    assert phrase.frequency == 5
    assert phrase.first_seen == 1234567.0


def test_danmaku_buffer_defaults():
    """DanmakuBuffer should be instantiable with defaults."""
    from animetta.services.bilibili import DanmakuBuffer

    buf = DanmakuBuffer()
    assert buf is not None


def test_danmaku_buffer_custom_size():
    """DanmakuBuffer should accept custom max_size."""
    from animetta.services.bilibili import DanmakuBuffer

    buf = DanmakuBuffer(max_size=50)
    assert buf is not None


def test_meme_candidate_raw_creation():
    """MemeCandidateRaw should hold text, source, and metadata."""
    from animetta.services.bilibili import MemeCandidate

    candidate = MemeCandidate(
        text="绝绝子",
        context_hint="美食视频弹幕高频出现",
        tags=["food", "positive"],
    )
    assert candidate.text == "绝绝子"
    assert "food" in candidate.tags


# ── Analyzer prompt exists ──────────────────────────────────────────


def test_cognitive_analysis_prompt_exists():
    """The analyzer should have a system prompt template."""
    from animetta.services.meme.analyzer import COGNITIVE_ANALYSIS_SYSTEM_PROMPT

    assert len(COGNITIVE_ANALYSIS_SYSTEM_PROMPT) > 100
    assert "认知" in COGNITIVE_ANALYSIS_SYSTEM_PROMPT


# ── Collector prompts + stopwords ───────────────────────────────────


def test_collector_stopwords_exist():
    """The collector should define Chinese stopwords for filtering."""
    from animetta.services.bilibili.text_utils import STOPWORDS

    assert len(STOPWORDS) > 10
    assert "的" in STOPWORDS
    assert "了" in STOPWORDS


def test_collector_meme_prompts_exist():
    """The collector should have meme identification prompts."""
    from animetta.services.bilibili.meme_collector import (
        MEME_IDENTIFY_SYSTEM_PROMPT,
        MEME_IDENTIFY_USER_PROMPT,
    )

    assert len(MEME_IDENTIFY_SYSTEM_PROMPT) > 50
    assert len(MEME_IDENTIFY_USER_PROMPT) > 50
