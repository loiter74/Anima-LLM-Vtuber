from __future__ import annotations

from animetta.avatar.analyzers.base import EmotionData
from animetta.avatar.analyzers.llm_tag import EmotionExtractionResult, StandaloneLLMTagAnalyzer

"""
Tests for StandaloneLLMTagAnalyzer — emotion tag extraction from LLM text.
"""


import pytest


class TestStandaloneLLMTagAnalyzerInit:
    """Initialization."""

    def test_default_init(self):
        """Default valid_emotions is None (accept all tags)."""
        analyzer = StandaloneLLMTagAnalyzer()
        assert analyzer.valid_emotions is None
        assert analyzer._confidence_mode == "binary"

    def test_valid_emotions_set(self):
        """Custom valid_emotions should be stored as a set."""
        analyzer = StandaloneLLMTagAnalyzer(valid_emotions=["happy", "sad"])
        assert analyzer.valid_emotions == {"happy", "sad"}

    def test_invalid_confidence_mode_raises(self):
        """Unknown confidence_mode should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid confidence_mode"):
            StandaloneLLMTagAnalyzer(confidence_mode="invalid")

    def test_valid_confidence_modes(self):
        """All valid confidence modes should be accepted."""
        for mode in ("binary", "frequency", "normalized"):
            analyzer = StandaloneLLMTagAnalyzer(confidence_mode=mode)
            assert analyzer._confidence_mode == mode


class TestStandaloneLLMTagAnalyzerExtract:
    """extract() — new interface."""

    def test_single_tag(self):
        """Single [happy] tag should be extracted."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract("Hello [happy] world!")
        assert isinstance(result, EmotionData)
        assert result.primary == "happy"
        assert result.confidence == 1.0
        assert result.metadata["has_emotions"] is True
        assert result.metadata["cleaned_text"] == "Hello  world!"

    def test_multiple_tags(self):
        """Multiple different tags should all be extracted."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract("[happy] Hello [sad] world [angry]!")
        assert result.metadata["has_emotions"] is True
        assert result.primary == "happy"  # first one
        assert len(result.metadata["raw_emotions"]) == 3

    def test_no_tags(self):
        """Text without tags should return neutral."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract("Hello world, how are you?")
        assert result.primary == "neutral"
        assert result.confidence == 0.0
        assert result.metadata["has_emotions"] is False
        assert result.metadata["cleaned_text"] == "Hello world, how are you?"

    def test_empty_text_raises(self):
        """Empty text should raise ValueError."""
        analyzer = StandaloneLLMTagAnalyzer()
        with pytest.raises(ValueError, match="Invalid input text"):
            analyzer.extract("")

    def test_whitespace_text_raises(self):
        """Whitespace-only text should raise ValueError."""
        analyzer = StandaloneLLMTagAnalyzer()
        with pytest.raises(ValueError, match="Invalid input text"):
            analyzer.extract("   ")

    def test_valid_emotions_filter(self):
        """Tags not in valid_emotions should be ignored."""
        analyzer = StandaloneLLMTagAnalyzer(valid_emotions=["happy", "sad"])
        result = analyzer.extract("[happy] Hello [angry] world!")
        assert result.primary == "happy"
        # Only 1 tag extracted (angry is filtered)
        assert len(result.metadata["raw_emotions"]) == 1

    def test_case_insensitive(self):
        """Tags should be case-insensitive."""
        analyzer = StandaloneLLMTagAnalyzer(valid_emotions=["happy"])
        result = analyzer.extract("[HAPPY] Hello!")
        assert result.primary == "happy"
        assert result.metadata["has_emotions"] is True

    def test_confidence_binary(self):
        """Binary mode: has tag = 1.0."""
        analyzer = StandaloneLLMTagAnalyzer(confidence_mode="binary")
        result = analyzer.extract("[happy] text")
        assert result.confidence == 1.0

    def test_confidence_frequency(self):
        """Frequency mode: based on tag count relative to text length."""
        analyzer = StandaloneLLMTagAnalyzer(confidence_mode="frequency")
        result = analyzer.extract("[happy] [happy] [sad] short")
        # 3 tags, cleaned text length ~12 chars, min(3/10, 1.0) = 0.3
        assert 0.0 < result.confidence <= 1.0

    def test_confidence_no_emotion(self):
        """No extracted tag should give 0.0 confidence."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract("Hello world")
        assert result.confidence == 0.0

    def test_cleaned_text_no_tags(self):
        """Cleaned text should equal original when no tags present."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract("Hello world")
        assert result.metadata["cleaned_text"] == "Hello world"

    def test_cleaned_text_removes_all_tags(self):
        """All tag brackets should be removed from cleaned text."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract("[happy] A [sad] B [angry] C")
        cleaned = result.metadata["cleaned_text"]
        assert "[" not in cleaned
        assert "]" not in cleaned


class TestStandaloneLLMTagAnalyzerExtractLegacy:
    """extract_legacy() — legacy format."""

    def test_returns_emotion_extraction_result(self):
        """extract_legacy should return EmotionExtractionResult."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract_legacy("[happy] Hello")
        assert isinstance(result, EmotionExtractionResult)
        assert result.has_emotions is True
        assert len(result.emotions) == 1
        assert result.emotions[0].emotion == "happy"

    def test_empty_text_returns_empty(self):
        """Empty text should return empty result."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract_legacy("")
        assert result.has_emotions is False
        assert result.emotions == []
        assert result.cleaned_text == ""

    def test_valid_emotions_filter_legacy(self):
        """Legacy method should also respect valid_emotions."""
        analyzer = StandaloneLLMTagAnalyzer(valid_emotions=["happy"])
        result = analyzer.extract_legacy("[happy] [angry] text")
        assert len(result.emotions) == 1
        assert result.emotions[0].emotion == "happy"

    def test_multiple_same_tags(self):
        """Multiple occurrences of same tag should all be captured."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer.extract_legacy("[happy] X [happy] Y")
        assert len(result.emotions) == 2
        assert all(t.emotion == "happy" for t in result.emotions)


class TestStandaloneLLMTagAnalyzerHelpers:
    """Internal helper methods."""

    def test_remove_segments_empty(self):
        """_remove_segments with empty segments returns original text."""
        analyzer = StandaloneLLMTagAnalyzer()
        text = "Hello [happy] world"
        result = analyzer._remove_segments(text, [])
        assert result == text

    def test_remove_segments_multiple(self):
        """_remove_segments should remove multiple segments in reverse order."""
        analyzer = StandaloneLLMTagAnalyzer()
        text = "A [happy] B [sad] C"
        segments = [(2, 9), (12, 17)]
        result = analyzer._remove_segments(text, segments)
        assert result == "A  B  C"

    def test_build_timeline(self):
        """_build_timeline should create correct timeline entries."""
        analyzer = StandaloneLLMTagAnalyzer()
        legacy = analyzer.extract_legacy("[happy] A [sad] B")
        timeline = analyzer._build_timeline(legacy)
        assert len(timeline) == 2
        assert timeline[0]["emotion"] == "happy"
        assert timeline[1]["emotion"] == "sad"

    def test_extract_primary_with_emotions(self):
        """_extract_primary returns first emotion."""
        analyzer = StandaloneLLMTagAnalyzer()
        legacy = analyzer.extract_legacy("[happy] [sad]")
        assert analyzer._extract_primary(legacy) == "happy"

    def test_extract_primary_without_emotions(self):
        """_extract_primary returns 'neutral' when no emotions."""
        analyzer = StandaloneLLMTagAnalyzer()
        legacy = analyzer.extract_legacy("no tags")
        assert analyzer._extract_primary(legacy) == "neutral"

    def test_count_emotions(self):
        """_count_emotions should correctly count occurrences."""
        analyzer = StandaloneLLMTagAnalyzer()
        legacy = analyzer.extract_legacy("[happy] [sad] [happy]")
        counts = analyzer._count_emotions(legacy)
        assert counts == {"happy": 2, "sad": 1}

    def test_get_default_emotion_data(self):
        """_get_default_emotion_data should return neutral with 0 confidence."""
        analyzer = StandaloneLLMTagAnalyzer()
        result = analyzer._get_default_emotion_data("test text")
        assert result.primary == "neutral"
        assert result.confidence == 0.0
        assert result.metadata["has_emotions"] is False
        assert result.metadata["cleaned_text"] == "test text"


class TestStandaloneLLMTagAnalyzerProperties:
    """Properties and metadata."""

    def test_name(self):
        """name property should return correct value."""
        analyzer = StandaloneLLMTagAnalyzer()
        assert analyzer.name == "standalone_llm_tag_analyzer"

    def test_priority(self):
        """Priority should be 1 (highest)."""
        analyzer = StandaloneLLMTagAnalyzer()
        assert analyzer.priority == 1

    def test_get_supported_emotions_with_valid(self):
        """get_supported_emotions should return valid_emotions list."""
        analyzer = StandaloneLLMTagAnalyzer(valid_emotions=["a", "b"])
        assert sorted(analyzer.get_supported_emotions()) == ["a", "b"]

    def test_get_supported_emotions_empty(self):
        """get_supported_emotions should return empty list when no valid_emotions."""
        analyzer = StandaloneLLMTagAnalyzer()
        assert analyzer.get_supported_emotions() == []

    def test_validate_input_valid(self):
        """validate_input returns True for non-empty text."""
        analyzer = StandaloneLLMTagAnalyzer()
        assert analyzer.validate_input("hello") is True

    def test_validate_input_invalid(self):
        """validate_input returns False for empty/whitespace text."""
        analyzer = StandaloneLLMTagAnalyzer()
        assert analyzer.validate_input("") is False
        assert analyzer.validate_input("   ") is False
        assert analyzer.validate_input(123) is False
