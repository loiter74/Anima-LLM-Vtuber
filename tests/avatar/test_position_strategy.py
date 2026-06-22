from __future__ import annotations

from animetta.avatar.strategies.base import TimelineConfig, TimelineSegment
from animetta.avatar.strategies.position import PositionBasedStrategy

"""
Tests for PositionBasedStrategy — even time distribution of emotion segments.
"""

import pytest

# ============================================================
# Initialization
# ============================================================

class TestPositionBasedStrategyInit:
    """Initialization."""

    def test_default_init(self):
        """Default init should create valid strategy."""
        strategy = PositionBasedStrategy()
        assert strategy._enable_smoothing is True
        assert strategy.core.config.default_emotion == "neutral"

    def test_custom_config(self):
        """Custom config should be honored."""
        config = TimelineConfig(default_emotion="happy", min_segment_duration=0.5)
        strategy = PositionBasedStrategy(config=config)
        assert strategy.core.config.default_emotion == "happy"
        assert strategy.core.config.min_segment_duration == 0.5

    def test_smoothing_disabled(self):
        """Smoothing can be disabled."""
        strategy = PositionBasedStrategy(enable_smoothing=False)
        assert strategy._enable_smoothing is False


# ============================================================
# calculate
# ============================================================

class TestPositionBasedStrategyCalculate:
    """calculate() — even time distribution."""

    def test_single_emotion(self):
        """Single emotion should fill entire duration."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate(["happy"], "Hello", audio_duration=10.0)
        assert len(segments) == 1
        assert segments[0].emotion == "happy"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 10.0

    def test_two_emotions_even_split(self):
        """Two emotions should split time evenly."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate(["happy", "sad"], "Hello world", audio_duration=10.0)
        assert len(segments) == 2
        assert segments[0].emotion == "happy"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 5.0
        assert segments[1].emotion == "sad"
        assert segments[1].start_time == 5.0
        assert segments[1].end_time == 10.0

    def test_three_emotions_equal_split(self):
        """Three emotions should split time into thirds."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate(["a", "b", "c"], "text", audio_duration=9.0)
        assert len(segments) == 3
        assert segments[0].end_time == 3.0
        assert segments[1].start_time == 3.0
        assert segments[1].end_time == 6.0
        assert segments[2].start_time == 6.0
        assert segments[2].end_time == 9.0

    def test_no_emotions_returns_default(self):
        """Empty emotions list should return single default segment."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate([], "Hello", audio_duration=5.0)
        assert len(segments) == 1
        assert segments[0].emotion == "neutral"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 5.0

    def test_emotions_none_raises(self):
        """None emotions (invalid) should raise ValueError."""
        strategy = PositionBasedStrategy()
        with pytest.raises(ValueError, match="Invalid input"):
            strategy.calculate(None, "text", 5.0)  # type: ignore

    def test_zero_duration_raises(self):
        """Zero duration should raise ValueError."""
        strategy = PositionBasedStrategy()
        with pytest.raises(ValueError, match="Invalid input"):
            strategy.calculate(["happy"], "text", 0.0)

    def test_negative_duration_raises(self):
        """Negative duration should raise ValueError."""
        strategy = PositionBasedStrategy()
        with pytest.raises(ValueError, match="Invalid input"):
            strategy.calculate(["happy"], "text", -1.0)

    def test_non_string_text_raises(self):
        """Non-string text should raise ValueError."""
        strategy = PositionBasedStrategy()
        with pytest.raises(ValueError, match="Invalid input"):
            strategy.calculate(["happy"], 123, 5.0)  # type: ignore


# ============================================================
# Smoothing (merge adjacent same emotions)
# ============================================================

class TestPositionBasedStrategySmoothing:
    """Adjacent same emotion merging."""

    def test_merge_adjacent_same_emotions(self):
        """Adjacent same emotions should be merged when smoothing enabled."""
        strategy = PositionBasedStrategy(enable_smoothing=True)
        segments = strategy.calculate(
            ["happy", "happy", "sad"], "text", audio_duration=9.0
        )
        assert len(segments) == 2  # happy merged, sad remains
        assert segments[0].emotion == "happy"
        assert segments[1].emotion == "sad"

    def test_no_merge_when_smoothing_disabled(self):
        """Adjacent same emotions should NOT be merged when smoothing disabled."""
        strategy = PositionBasedStrategy(enable_smoothing=False)
        segments = strategy.calculate(
            ["happy", "happy", "sad"], "text", audio_duration=9.0
        )
        assert len(segments) == 3

    def test_merge_multiple_groups(self):
        """Multiple groups of same emotions should each be merged."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate(
            ["happy", "happy", "sad", "sad"], "text", audio_duration=8.0
        )
        assert len(segments) == 2
        assert segments[0].emotion == "happy"
        assert segments[1].emotion == "sad"


# ============================================================
# Full coverage
# ============================================================

class TestPositionBasedStrategyCoverage:
    """Full audio duration coverage."""

    def test_segments_cover_full_duration(self):
        """Segments should cover the entire audio duration."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate(["happy", "sad"], "text", audio_duration=7.5)
        total = sum(s.duration for s in segments)
        assert abs(total - 7.5) < 0.01

    def test_single_segment_covers_full(self):
        """Single segment should cover full duration."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate(["happy"], "text", audio_duration=10.0)
        assert abs(segments[0].duration - 10.0) < 0.01

    def test_default_segment_covers_empty(self):
        """Default segment with no emotions should cover full duration."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate([], "text", audio_duration=3.0)
        assert abs(segments[0].duration - 3.0) < 0.01


# ============================================================
# Segment info
# ============================================================

class TestPositionBasedStrategySegmentInfo:
    """get_segment_info()."""

    def test_get_segment_info_with_segments(self):
        """get_segment_info should return correct stats."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate(["happy", "sad"], "text", audio_duration=6.0)
        info = strategy.get_segment_info(segments)
        assert info["count"] == 2
        assert abs(info["total_duration"] - 6.0) < 0.01
        assert "happy" in info["emotions"]
        assert "sad" in info["emotions"]
        assert info["emotion_counts"]["happy"] == 1

    def test_get_segment_info_empty(self):
        """get_segment_info with empty list should return zeros."""
        strategy = PositionBasedStrategy()
        info = strategy.get_segment_info([])
        assert info["count"] == 0
        assert info["total_duration"] == 0.0

    def test_get_segment_info_min_max_duration(self):
        """get_segment_info should include min/max duration."""
        strategy = PositionBasedStrategy()
        segments = strategy.calculate(["a", "b", "c"], "text", audio_duration=9.0)
        info = strategy.get_segment_info(segments)
        assert info["min_duration"] > 0
        assert info["max_duration"] > 0
        assert info["average_duration"] > 0


# ============================================================
# Filter short segments
# ============================================================

class TestPositionBasedStrategyFilter:
    """Short segment filtering."""

    def test_filter_short_segments_removes_short(self):
        """Segments shorter than min_duration should be filtered."""
        strategy = PositionBasedStrategy()
        segments = [
            TimelineSegment("a", 0.0, 0.05, 1.0),
            TimelineSegment("b", 0.05, 5.0, 1.0),
        ]
        result = strategy._filter_short_segments(segments, min_duration=0.1)
        assert len(result) == 1
        assert result[0].emotion == "b"

    def test_filter_short_all_filtered_keeps_longest(self):
        """When all segments are too short, keep the longest."""
        strategy = PositionBasedStrategy()
        segments = [
            TimelineSegment("a", 0.0, 0.04, 1.0),
            TimelineSegment("b", 0.04, 0.08, 1.0),
        ]
        result = strategy._filter_short_segments(segments, min_duration=0.1)
        assert len(result) == 1
        # b (0.04) is longer than a (0.04), but they have same duration so either works


# ============================================================
# Properties
# ============================================================

class TestPositionBasedStrategyProperties:
    """Properties."""

    def test_name(self):
        """name property should return correct value."""
        strategy = PositionBasedStrategy()
        assert strategy.name == "position_based"

    def test_validate_input_valid(self):
        """validate_input returns True for valid inputs."""
        strategy = PositionBasedStrategy()
        assert strategy.validate_input(["happy"], "text", 5.0) is True

    def test_validate_input_invalid_duration(self):
        """validate_input returns False for invalid duration."""
        strategy = PositionBasedStrategy()
        assert strategy.validate_input(["happy"], "text", 0) is False
        assert strategy.validate_input(["happy"], "text", -1) is False

    def test_validate_input_none_emotions(self):
        """validate_input returns False for None emotions."""
        strategy = PositionBasedStrategy()
        assert strategy.validate_input(None, "text", 5.0) is False
