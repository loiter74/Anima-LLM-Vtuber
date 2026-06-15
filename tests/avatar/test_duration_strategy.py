from __future__ import annotations

from animetta.avatar.strategies.duration import DurationBasedStrategy

"""
Tests for DurationBasedStrategy — emotion-weight based time allocation.
"""

import pytest

# ============================================================
# Initialization
# ============================================================

class TestDurationBasedStrategyInit:
    """Initialization."""

    def test_default_init(self):
        """Default init should use DEFAULT_DURATION_WEIGHTS."""
        strategy = DurationBasedStrategy()
        assert strategy._duration_weights["happy"] == 1.0
        assert strategy._duration_weights["sad"] == 1.5
        assert strategy._min_emotion_duration == 0.5
        assert strategy._max_emotion_duration == 5.0

    def test_custom_weights(self):
        """Custom weights should override defaults."""
        weights = {"happy": 2.0, "neutral": 0.5}
        strategy = DurationBasedStrategy(duration_weights=weights)
        assert strategy._duration_weights == weights
        assert "sad" not in strategy._duration_weights

    def test_custom_min_max(self):
        """Custom min/max duration should be honored."""
        strategy = DurationBasedStrategy(
            min_emotion_duration=1.0, max_emotion_duration=3.0
        )
        assert strategy._min_emotion_duration == 1.0
        assert strategy._max_emotion_duration == 3.0

    def test_smoothing_disabled(self):
        """Smoothing can be disabled."""
        strategy = DurationBasedStrategy(enable_smoothing=False)
        assert strategy._enable_smoothing is False


# ============================================================
# Weight-based allocation
# ============================================================

class TestDurationBasedStrategyWeights:
    """Emotion-weight based time allocation."""

    def test_sad_gets_longer_than_happy(self):
        """Sad (weight 1.5) should get more time than happy (weight 1.0)."""
        strategy = DurationBasedStrategy()
        segments = strategy.calculate(
            ["happy", "sad"], "text", audio_duration=10.0
        )
        assert len(segments) == 2
        # sad has higher weight, so should get more time
        assert segments[1].duration > segments[0].duration

    def test_surprised_shorter_than_happy(self):
        """Surprised (weight 0.8) should get less time than happy (weight 1.0).
        Use higher max duration to avoid clamping; three emotions so last-one
        extension doesn't affect the comparison of first two."""
        strategy = DurationBasedStrategy(max_emotion_duration=10.0)
        segments = strategy.calculate(
            ["happy", "surprised", "neutral"], "text", audio_duration=15.0
        )
        # happy has higher weight → more time than surprised
        assert len(segments) >= 2
        assert segments[0].emotion == "happy"
        assert segments[1].emotion == "surprised"
        assert segments[1].duration < segments[0].duration

    def test_thinking_longer_than_neutral(self):
        """Thinking (weight 1.3) should get more time than neutral (weight 1.0)."""
        strategy = DurationBasedStrategy()
        segments = strategy.calculate(
            ["neutral", "thinking"], "text", audio_duration=10.0
        )
        assert segments[1].duration > segments[0].duration

    def test_unknown_emotion_default_weight(self):
        """Unknown emotion should use default weight of 1.0."""
        strategy = DurationBasedStrategy()
        segments = strategy.calculate(
            ["happy", "unknown_emotion"], "text", audio_duration=10.0
        )
        assert len(segments) == 2
        # Both weight 1.0, so equal time
        assert abs(segments[0].duration - segments[1].duration) < 0.1

    def test_same_emotions_equal_time(self):
        """Same emotions with same weight should get equal time.
        Disable smoothing to prevent merge."""
        strategy = DurationBasedStrategy(enable_smoothing=False)
        segments = strategy.calculate(
            ["happy", "happy"], "text", audio_duration=10.0
        )
        assert len(segments) == 2
        assert abs(segments[0].duration - segments[1].duration) < 0.1

    def test_last_emotion_extends_to_end(self):
        """Last emotion should always extend to audio_duration end."""
        strategy = DurationBasedStrategy()
        segments = strategy.calculate(
            ["happy", "sad"], "text", audio_duration=10.0
        )
        assert segments[-1].end_time == 10.0


# ============================================================
# No emotions
# ============================================================

class TestDurationBasedStrategyNoEmotions:
    """Behavior when no emotions provided."""

    def test_empty_list_returns_default(self):
        """Empty emotions list should return single default segment."""
        strategy = DurationBasedStrategy()
        segments = strategy.calculate([], "text", audio_duration=5.0)
        assert len(segments) == 1
        assert segments[0].emotion == "neutral"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 5.0

    def test_none_emotions_raises(self):
        """None emotions should raise ValueError."""
        strategy = DurationBasedStrategy()
        with pytest.raises(ValueError, match="Invalid input"):
            strategy.calculate(None, "text", 5.0)  # type: ignore


# ============================================================
# Min/max duration constraints
# ============================================================

class TestDurationBasedStrategyConstraints:
    """Min/max duration constraints."""

    def test_min_duration_enforced(self):
        """No segment should be shorter than min_emotion_duration."""
        strategy = DurationBasedStrategy(min_emotion_duration=2.0)
        # Many emotions with short total duration — each should be at least 2.0
        segments = strategy.calculate(
            ["happy", "sad", "angry", "surprised"],
            "text", audio_duration=4.0
        )
        for seg in segments:
            assert seg.duration >= 2.0 - 0.01

    def test_max_duration_enforced(self):
        """Non-last segments should respect max_emotion_duration.
        Last segment always extends to audio_duration end."""
        strategy = DurationBasedStrategy(max_emotion_duration=1.0)
        segments = strategy.calculate(
            ["happy", "sad", "neutral"], "text", audio_duration=10.0
        )
        # The first two segments should be clamped to max_emotion_duration
        for i, seg in enumerate(segments):
            if i < len(segments) - 1:
                assert seg.duration <= 1.0 + 0.01, f"Segment {i} ({seg.emotion}) duration {seg.duration} > max"


# ============================================================
# Weight management
# ============================================================

class TestDurationBasedStrategyWeightManagement:
    """set_duration_weight and get_duration_weight."""

    def test_set_duration_weight(self):
        """set_duration_weight should update weight for an emotion."""
        strategy = DurationBasedStrategy()
        strategy.set_duration_weight("happy", 3.0)
        assert strategy._duration_weights["happy"] == 3.0

    def test_set_duration_weight_zero_raises(self):
        """Setting weight to 0 or negative should raise."""
        strategy = DurationBasedStrategy()
        with pytest.raises(ValueError, match="Weight must be greater than 0"):
            strategy.set_duration_weight("happy", 0)
        with pytest.raises(ValueError, match="Weight must be greater than 0"):
            strategy.set_duration_weight("happy", -1)

    def test_get_duration_weight_existing(self):
        """get_duration_weight should return correct weight."""
        strategy = DurationBasedStrategy()
        assert strategy.get_duration_weight("sad") == 1.5

    def test_get_duration_weight_unknown(self):
        """get_duration_weight for unknown emotion should return 1.0."""
        strategy = DurationBasedStrategy()
        assert strategy.get_duration_weight("unknown") == 1.0


# ============================================================
# Segment info
# ============================================================

class TestDurationBasedStrategySegmentInfo:
    """get_segment_info()."""

    def test_get_segment_info_with_segments(self):
        """get_segment_info should return stats including emotion_durations."""
        strategy = DurationBasedStrategy()
        segments = strategy.calculate(["happy", "sad"], "text", audio_duration=10.0)
        info = strategy.get_segment_info(segments)
        assert info["count"] == 2
        assert "emotion_durations" in info
        assert "happy" in info["emotion_durations"]
        assert "sad" in info["emotion_durations"]

    def test_get_segment_info_empty(self):
        """get_segment_info with empty list should return zeros."""
        strategy = DurationBasedStrategy()
        info = strategy.get_segment_info([])
        assert info["count"] == 0
        assert info["total_duration"] == 0.0


# ============================================================
# Properties
# ============================================================

class TestDurationBasedStrategyProperties:
    """Properties."""

    def test_name(self):
        """name property should return correct value."""
        strategy = DurationBasedStrategy()
        assert strategy.name == "duration_based"

    def test_validate_input_valid(self):
        """validate_input returns True for valid inputs."""
        strategy = DurationBasedStrategy()
        assert strategy.validate_input(["happy"], "text", 5.0) is True

    def test_validate_input_invalid(self):
        """validate_input returns False for invalid inputs."""
        strategy = DurationBasedStrategy()
        assert strategy.validate_input(["happy"], "text", 0) is False
        assert strategy.validate_input(["happy"], "text", -1) is False
        assert strategy.validate_input(None, "text", 5.0) is False
