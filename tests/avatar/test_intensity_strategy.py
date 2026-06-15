from __future__ import annotations

from animetta.avatar.strategies.intensity import IntensityBasedStrategy

"""
Tests for IntensityBasedStrategy — intensity-based time allocation.
"""

import pytest

# ============================================================
# Initialization
# ============================================================

class TestIntensityBasedStrategyInit:
    """Initialization."""

    def test_default_init(self):
        """Default init should use DEFAULT_EMOTION_INTENSITIES."""
        strategy = IntensityBasedStrategy()
        assert strategy._emotion_intensities["happy"] == 0.8
        assert strategy._emotion_intensities["angry"] == 0.9
        assert strategy._min_intensity == 0.2
        assert strategy._intensity_factor == 0.5

    def test_custom_intensities(self):
        """Custom emotion intensities should override defaults."""
        intensities = {"happy": 1.0, "neutral": 0.1}
        strategy = IntensityBasedStrategy(emotion_intensities=intensities)
        assert strategy._emotion_intensities == intensities
        assert "sad" not in strategy._emotion_intensities

    def test_custom_min_intensity(self):
        """Custom min_intensity should be honored."""
        strategy = IntensityBasedStrategy(min_intensity=0.5)
        assert strategy._min_intensity == 0.5

    def test_custom_intensity_factor(self):
        """Custom intensity_factor should be honored."""
        strategy = IntensityBasedStrategy(intensity_factor=0.8)
        assert strategy._intensity_factor == 0.8

    def test_intensity_factor_clamped(self):
        """intensity_factor should be clamped to [0, 1]."""
        strategy = IntensityBasedStrategy(intensity_factor=1.5)
        assert strategy._intensity_factor == 1.0
        strategy2 = IntensityBasedStrategy(intensity_factor=-0.5)
        assert strategy2._intensity_factor == 0.0

    def test_smoothing_disabled(self):
        """Smoothing can be disabled."""
        strategy = IntensityBasedStrategy(enable_smoothing=False)
        assert strategy._enable_smoothing is False


# ============================================================
# Intensity-based weighting
# ============================================================

class TestIntensityBasedStrategyWeights:
    """Intensity-based time and intensity allocation."""

    def test_higher_intensity_gets_more_time(self):
        """Higher intensity emotions should get more time (with factor > 0)."""
        strategy = IntensityBasedStrategy(intensity_factor=1.0)  # full intensity influence
        segments = strategy.calculate(
            ["happy", "neutral"], "text", audio_duration=10.0
        )
        # happy (0.8) > neutral (0.3), so happy gets more time
        assert len(segments) == 2
        assert segments[0].duration > segments[1].duration

    def test_intensity_factor_zero_equal_time(self):
        """intensity_factor=0 should give equal time regardless of intensity."""
        strategy = IntensityBasedStrategy(intensity_factor=0.0)
        segments = strategy.calculate(
            ["happy", "neutral", "angry"], "text", audio_duration=9.0
        )
        # All should have roughly equal time
        assert abs(segments[0].duration - 3.0) < 0.01
        assert abs(segments[1].duration - 3.0) < 0.01
        assert abs(segments[2].duration - 3.0) < 0.01

    def test_intensity_values_in_segments(self):
        """Each segment should carry its emotion's intensity value."""
        strategy = IntensityBasedStrategy()
        segments = strategy.calculate(
            ["happy", "angry"], "text", audio_duration=10.0
        )
        # happy intensity = 0.8, angry intensity = 0.9
        assert segments[0].intensity == 0.8
        assert segments[1].intensity == 0.9

    def test_last_emotion_extends_to_end(self):
        """Last emotion should always extend to audio_duration end."""
        strategy = IntensityBasedStrategy()
        segments = strategy.calculate(
            ["happy", "sad"], "text", audio_duration=10.0
        )
        assert segments[-1].end_time == 10.0


# ============================================================
# Low intensity filtering
# ============================================================

class TestIntensityBasedStrategyFiltering:
    """Low intensity emotion filtering."""

    def test_below_min_intensity_filtered(self):
        """Emotions below min_intensity should be filtered out."""
        strategy = IntensityBasedStrategy(min_intensity=0.5)
        segments = strategy.calculate(
            ["happy", "neutral"], "text", audio_duration=10.0
        )
        # neutral (0.3) is below 0.5, should be filtered
        assert len(segments) == 1
        assert segments[0].emotion == "happy"

    def test_all_below_min_intensity_returns_default(self):
        """When all emotions are below threshold, return default segment."""
        strategy = IntensityBasedStrategy(min_intensity=0.9)
        segments = strategy.calculate(
            ["happy", "neutral"], "text", audio_duration=5.0
        )
        assert len(segments) == 1
        assert segments[0].emotion == "neutral"  # default emotion
        assert segments[0].intensity == 0.5  # default intensity

    def test_unknown_emotion_default_intensity(self):
        """Unknown emotion should use default intensity of 0.5."""
        strategy = IntensityBasedStrategy(min_intensity=0.2)
        segments = strategy.calculate(
            ["unknown_emotion"], "text", audio_duration=5.0
        )
        assert len(segments) == 1
        # 0.5 >= 0.2, so it should pass
        assert segments[0].intensity == 0.5


# ============================================================
# No emotions
# ============================================================

class TestIntensityBasedStrategyNoEmotions:
    """Behavior when no emotions provided."""

    def test_empty_list_returns_default(self):
        """Empty emotions list should return single default segment."""
        strategy = IntensityBasedStrategy()
        segments = strategy.calculate([], "text", audio_duration=5.0)
        assert len(segments) == 1
        assert segments[0].emotion == "neutral"
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 5.0

    def test_none_emotions_raises(self):
        """None emotions should raise ValueError."""
        strategy = IntensityBasedStrategy()
        with pytest.raises(ValueError, match="Invalid input"):
            strategy.calculate(None, "text", 5.0)  # type: ignore


# ============================================================
# Intensity management
# ============================================================

class TestIntensityBasedStrategyIntensityManagement:
    """set_emotion_intensity and get_emotion_intensity."""

    def test_set_emotion_intensity(self):
        """set_emotion_intensity should update intensity for an emotion."""
        strategy = IntensityBasedStrategy()
        strategy.set_emotion_intensity("happy", 1.0)
        assert strategy._emotion_intensities["happy"] == 1.0

    def test_set_intensity_invalid_range(self):
        """Setting intensity outside [0, 1] should raise."""
        strategy = IntensityBasedStrategy()
        with pytest.raises(ValueError, match="must be between"):
            strategy.set_emotion_intensity("happy", 1.5)
        with pytest.raises(ValueError, match="must be between"):
            strategy.set_emotion_intensity("happy", -0.1)

    def test_get_emotion_intensity_existing(self):
        """get_emotion_intensity should return correct value."""
        strategy = IntensityBasedStrategy()
        assert strategy.get_emotion_intensity("angry") == 0.9

    def test_get_emotion_intensity_unknown(self):
        """get_emotion_intensity for unknown emotion should return 0.5."""
        strategy = IntensityBasedStrategy()
        assert strategy.get_emotion_intensity("unknown") == 0.5


# ============================================================
# Segment info
# ============================================================

class TestIntensityBasedStrategySegmentInfo:
    """get_segment_info()."""

    def test_get_segment_info_with_segments(self):
        """get_segment_info should include intensity stats."""
        strategy = IntensityBasedStrategy()
        segments = strategy.calculate(
            ["happy", "angry"], "text", audio_duration=10.0
        )
        info = strategy.get_segment_info(segments)
        assert info["count"] == 2
        assert "average_intensity" in info
        assert "emotion_intensities" in info
        assert 0 < info["average_intensity"] <= 1.0

    def test_get_segment_info_empty(self):
        """get_segment_info with empty list should return zeros."""
        strategy = IntensityBasedStrategy()
        info = strategy.get_segment_info([])
        assert info["count"] == 0
        assert info["total_duration"] == 0.0
        assert info["average_intensity"] == 0.0

    def test_get_segment_info_emotion_intensities(self):
        """get_segment_info should include per-emotion average intensities."""
        strategy = IntensityBasedStrategy()
        segments = strategy.calculate(
            ["happy", "angry"], "text", audio_duration=10.0
        )
        info = strategy.get_segment_info(segments)
        assert "happy" in info["emotion_intensities"]
        assert "angry" in info["emotion_intensities"]
        assert info["emotion_intensities"]["happy"] == 0.8
        assert info["emotion_intensities"]["angry"] == 0.9


# ============================================================
# Properties
# ============================================================

class TestIntensityBasedStrategyProperties:
    """Properties."""

    def test_name(self):
        """name property should return correct value."""
        strategy = IntensityBasedStrategy()
        assert strategy.name == "intensity_based"

    def test_validate_input_valid(self):
        """validate_input returns True for valid inputs."""
        strategy = IntensityBasedStrategy()
        assert strategy.validate_input(["happy"], "text", 5.0) is True

    def test_validate_input_invalid(self):
        """validate_input returns False for invalid inputs."""
        strategy = IntensityBasedStrategy()
        assert strategy.validate_input(["happy"], "text", 0) is False
        assert strategy.validate_input(["happy"], "text", -1) is False
        assert strategy.validate_input(None, "text", 5.0) is False
