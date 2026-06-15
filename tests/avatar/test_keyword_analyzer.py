from __future__ import annotations

from animetta.avatar.analyzers.base import EmotionData
from animetta.avatar.analyzers.keyword import KeywordAnalyzer

"""
Tests for KeywordAnalyzer — emotion detection via Chinese keyword matching.
"""

import pytest

# ============================================================
# Initialization
# ============================================================

class TestKeywordAnalyzerInit:
    """Initialization."""

    def test_default_init(self):
        """Default init should use DEFAULT_KEYWORDS and weighted mode."""
        analyzer = KeywordAnalyzer()
        assert analyzer.keywords is not None
        assert "happy" in analyzer.keywords
        assert "sad" in analyzer.keywords
        assert analyzer._confidence_mode == "weighted"

    def test_custom_keywords(self):
        """Custom keyword mapping should override defaults."""
        custom = {"happy": ["开心"]}
        analyzer = KeywordAnalyzer(keywords=custom)
        assert analyzer.keywords == custom
        assert "sad" not in analyzer.keywords

    def test_invalid_confidence_mode_raises(self):
        """Unknown confidence_mode should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid confidence_mode"):
            KeywordAnalyzer(confidence_mode="invalid")

    def test_valid_confidence_modes(self):
        """All valid confidence modes should be accepted."""
        for mode in ("count", "weighted", "normalized", "binary"):
            analyzer = KeywordAnalyzer(confidence_mode=mode)
            assert analyzer._confidence_mode == mode


# ============================================================
# Emotion extraction
# ============================================================

class TestKeywordAnalyzerExtract:
    """extract() — emotion detection from text."""

    def test_happy_detected(self):
        """Text with happy keywords should detect happy."""
        analyzer = KeywordAnalyzer()
        result = analyzer.extract("我今天好开心啊！哈哈！")
        assert isinstance(result, EmotionData)
        assert result.primary == "happy"
        assert result.confidence > 0

    def test_sad_detected(self):
        """Text with sad keywords should detect sad."""
        analyzer = KeywordAnalyzer()
        result = analyzer.extract("我好难过，呜呜，伤心。")
        assert result.primary == "sad"

    def test_angry_detected(self):
        """Text with angry keywords should detect angry."""
        analyzer = KeywordAnalyzer()
        result = analyzer.extract("真是气死我了！太可恶了！哼！")
        assert result.primary == "angry"

    def test_surprised_detected(self):
        """Text with surprised keywords should detect surprised."""
        analyzer = KeywordAnalyzer()
        result = analyzer.extract("哇！真的吗？太让人震惊了！")
        assert result.primary == "surprised"

    def test_multiple_emotions_picks_highest(self):
        """When multiple emotions matched, pick the one with most keywords."""
        analyzer = KeywordAnalyzer()
        # Text with more happy keywords than others
        result = analyzer.extract("开心！快乐！高兴！好吧。")
        assert result.primary == "happy"

    def test_no_match_returns_neutral(self):
        """Text with no keyword matches should return neutral with 0 confidence."""
        analyzer = KeywordAnalyzer()
        result = analyzer.extract("今天天气不错。")
        assert result.primary == "neutral"
        assert result.confidence == 0.0

    def test_empty_text_raises(self):
        """Empty text should raise ValueError."""
        analyzer = KeywordAnalyzer()
        with pytest.raises(ValueError, match="Invalid input text"):
            analyzer.extract("")

    def test_timeline_is_empty(self):
        """Keyword analyzer does not provide timeline info."""
        analyzer = KeywordAnalyzer()
        result = analyzer.extract("开心！")
        assert result.timeline == []

    def test_metadata_contains_scores(self):
        """Metadata should include score details."""
        analyzer = KeywordAnalyzer()
        result = analyzer.extract("开心！快乐！")
        assert "scores" in result.metadata
        assert result.metadata["source"] == "keyword"
        assert result.metadata["total_matches"] > 0
        assert result.metadata["matched_keywords"] > 0


# ============================================================
# Confidence modes
# ============================================================

class TestKeywordAnalyzerConfidenceModes:
    """Different confidence calculation modes."""

    def test_count_mode(self):
        """Count mode: confidence = min(max_score * 0.15, 1.0)."""
        analyzer = KeywordAnalyzer(confidence_mode="count")
        result = analyzer.extract("开心！开心！快乐！高兴！")
        # 3 happy keywords → min(3 * 0.15, 1.0) = 0.45
        assert 0.0 < result.confidence <= 1.0

    def test_count_mode_no_match(self):
        """Count mode with no match should return 0.0."""
        analyzer = KeywordAnalyzer(confidence_mode="count")
        result = analyzer.extract("今天天气不错。")
        assert result.confidence == 0.0

    def test_weighted_mode(self):
        """Weighted mode: confidence = min(max_score / text_length * 10, 1.0)."""
        analyzer = KeywordAnalyzer(confidence_mode="weighted")
        result = analyzer.extract("开心快乐！")
        assert 0.0 < result.confidence <= 1.0

    def test_normalized_mode(self):
        """Normalized mode: confidence = 1.0 when there's a match."""
        analyzer = KeywordAnalyzer(confidence_mode="normalized")
        result = analyzer.extract("开心！")
        assert result.confidence == 1.0

    def test_normalized_mode_no_match(self):
        """Normalized mode with no match should return 0.0."""
        analyzer = KeywordAnalyzer(confidence_mode="normalized")
        result = analyzer.extract("今天天气不错。")
        assert result.confidence == 0.0

    def test_binary_mode_with_match(self):
        """Binary mode: confidence = 0.5 when there's a match."""
        analyzer = KeywordAnalyzer(confidence_mode="binary")
        result = analyzer.extract("开心！")
        assert result.confidence == 0.5

    def test_binary_mode_no_match(self):
        """Binary mode: confidence = 0.0 when no match."""
        analyzer = KeywordAnalyzer(confidence_mode="binary")
        result = analyzer.extract("今天天气不错。")
        assert result.confidence == 0.0


# ============================================================
# Convenience methods
# ============================================================

class TestKeywordAnalyzerConvenience:
    """extract_emotion_tags and get_emotion_summary."""

    def test_extract_emotion_tags_matched(self):
        """extract_emotion_tags should return list of matched emotions."""
        analyzer = KeywordAnalyzer()
        tags = analyzer.extract_emotion_tags("开心！哈哈！")
        assert isinstance(tags, list)
        assert "happy" in tags

    def test_extract_emotion_tags_no_match(self):
        """extract_emotion_tags should return empty list when no match."""
        analyzer = KeywordAnalyzer()
        tags = analyzer.extract_emotion_tags("今天天气不错。")
        assert tags == []

    def test_get_emotion_summary(self):
        """get_emotion_summary should return full summary dict."""
        analyzer = KeywordAnalyzer()
        summary = analyzer.get_emotion_summary("开心！快乐！")
        assert isinstance(summary, dict)
        assert "primary" in summary
        assert "confidence" in summary
        assert "scores" in summary
        assert "total_matches" in summary
        assert "has_emotions" in summary
        assert summary["primary"] == "happy"
        assert summary["has_emotions"] is True

    def test_get_emotion_summary_no_match(self):
        """get_emotion_summary with no match should reflect neutral."""
        analyzer = KeywordAnalyzer()
        summary = analyzer.get_emotion_summary("今天天气不错。")
        assert summary["primary"] == "neutral"
        assert summary["has_emotions"] is False
        assert summary["total_matches"] == 0


# ============================================================
# Keyword management
# ============================================================

class TestKeywordAnalyzerKeywordManagement:
    """add_keywords and remove_keywords."""

    def test_add_keywords_new_emotion(self):
        """add_keywords should create a new emotion group."""
        analyzer = KeywordAnalyzer()
        analyzer.add_keywords("excited", ["太棒了", "厉害"])
        assert "excited" in analyzer.keywords
        assert len(analyzer.keywords["excited"]) == 2

    def test_add_keywords_existing_emotion(self):
        """add_keywords should append to existing emotion group."""
        analyzer = KeywordAnalyzer()
        analyzer.add_keywords("happy", ["超级开心"])
        assert "超级开心" in analyzer.keywords["happy"]

    def test_remove_keywords(self):
        """remove_keywords should remove specified keywords."""
        analyzer = KeywordAnalyzer()
        # Use a keyword that appears only once in the happy list
        analyzer.remove_keywords("happy", ["兴高采烈"])
        assert "兴高采烈" not in analyzer.keywords["happy"]

    def test_remove_keywords_nonexistent_emotion(self):
        """remove_keywords on nonexistent emotion should not raise."""
        analyzer = KeywordAnalyzer()
        analyzer.remove_keywords("nonexistent", ["word"])  # should not raise

    def test_remove_keywords_nonexistent_word(self):
        """remove_keywords on nonexistent word should not raise."""
        analyzer = KeywordAnalyzer()
        analyzer.remove_keywords("happy", ["nonexistent_word"])  # should not raise


# ============================================================
# Properties
# ============================================================

class TestKeywordAnalyzerProperties:
    """Properties and metadata."""

    def test_name(self):
        """name property should return correct value."""
        analyzer = KeywordAnalyzer()
        assert analyzer.name == "keyword_analyzer"

    def test_priority(self):
        """Priority should be 10 (lower than LLM tag)."""
        analyzer = KeywordAnalyzer()
        assert analyzer.priority == 10

    def test_get_supported_emotions(self):
        """get_supported_emotions should return emotion group keys."""
        analyzer = KeywordAnalyzer()
        emotions = analyzer.get_supported_emotions()
        assert "happy" in emotions
        assert "sad" in emotions
        assert "angry" in emotions

    def test_validate_input_valid(self):
        """validate_input returns True for valid text."""
        analyzer = KeywordAnalyzer()
        assert analyzer.validate_input("hello") is True

    def test_validate_input_invalid(self):
        """validate_input returns False for empty/whitespace/non-string."""
        analyzer = KeywordAnalyzer()
        assert analyzer.validate_input("") is False
        assert analyzer.validate_input("   ") is False
        assert analyzer.validate_input(None) is False
