from __future__ import annotations

from animetta.avatar.analyzers.base import EmotionData, IEmotionAnalyzer
from animetta.avatar.analyzers.keyword import KeywordAnalyzer
from animetta.avatar.analyzers.llm_tag import StandaloneLLMTagAnalyzer
from animetta.avatar.factory import (
    EmotionAnalyzerFactory,
    TimelineStrategyFactory,
    create_emotion_analyzer,
    create_timeline_strategy,
)
from animetta.avatar.strategies.base import ITimelineStrategy
from animetta.avatar.strategies.duration import DurationBasedStrategy
from animetta.avatar.strategies.intensity import IntensityBasedStrategy
from animetta.avatar.strategies.position import PositionBasedStrategy

"""
Tests for EmotionAnalyzerFactory and TimelineStrategyFactory.
"""

import pytest

# ============================================================
# EmotionAnalyzerFactory
# ============================================================

class TestEmotionAnalyzerFactory:
    """EmotionAnalyzerFactory create / register / list."""

    def test_create_llm_tag_analyzer(self):
        """Create llm_tag_analyzer with config."""
        analyzer = EmotionAnalyzerFactory.create(
            "llm_tag_analyzer",
            config={"valid_emotions": ["happy", "sad"]}
        )
        assert isinstance(analyzer, StandaloneLLMTagAnalyzer)
        assert analyzer.valid_emotions == {"happy", "sad"}

    def test_create_keyword_analyzer(self):
        """Create keyword_analyzer with config."""
        analyzer = EmotionAnalyzerFactory.create(
            "keyword_analyzer",
            config={"confidence_mode": "binary"}
        )
        assert isinstance(analyzer, KeywordAnalyzer)
        assert analyzer._confidence_mode == "binary"

    def test_create_without_config(self):
        """Create analyzer without config should use defaults."""
        analyzer = EmotionAnalyzerFactory.create("llm_tag_analyzer")
        assert isinstance(analyzer, StandaloneLLMTagAnalyzer)
        assert analyzer.valid_emotions is None

    def test_create_unknown_analyzer_raises(self):
        """Unknown analyzer name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown analyzer"):
            EmotionAnalyzerFactory.create("nonexistent_analyzer")

    def test_list_all_contains_builtins(self):
        """list_all should include built-in analyzers."""
        analyzers = EmotionAnalyzerFactory.list_all()
        assert "llm_tag_analyzer" in analyzers
        assert "keyword_analyzer" in analyzers

    def test_is_registered_true(self):
        """is_registered should return True for known analyzers."""
        assert EmotionAnalyzerFactory.is_registered("llm_tag_analyzer") is True

    def test_is_registered_false(self):
        """is_registered should return False for unknown analyzers."""
        assert EmotionAnalyzerFactory.is_registered("unknown") is False

    def test_register_new_analyzer(self):
        """Register a new custom analyzer."""
        class MockAnalyzer(IEmotionAnalyzer):
            def extract(self, text, context=None):
                return EmotionData(primary="neutral", confidence=0.0)
            @property
            def name(self):
                return "mock_analyzer"

        EmotionAnalyzerFactory.register("mock_test", MockAnalyzer)
        try:
            assert EmotionAnalyzerFactory.is_registered("mock_test") is True
            analyzer = EmotionAnalyzerFactory.create("mock_test")
            assert isinstance(analyzer, MockAnalyzer)
        finally:
            # Clean up registry
            EmotionAnalyzerFactory._analyzers.pop("mock_test", None)

    def test_register_non_interface_class_raises(self):
        """Registering a class that doesn't implement IEmotionAnalyzer should raise."""
        class NotAnAnalyzer:
            pass

        with pytest.raises(ValueError, match="must implement IEmotionAnalyzer"):
            EmotionAnalyzerFactory.register("invalid", NotAnAnalyzer)

    def test_register_overwrite_warning(self):
        """Registering an existing name should overwrite (no error)."""
        class MockAnalyzer(IEmotionAnalyzer):
            def extract(self, text, context=None):
                return EmotionData(primary="neutral", confidence=0.0)
            @property
            def name(self):
                return "mock2"

        EmotionAnalyzerFactory.register("llm_tag_analyzer", MockAnalyzer)
        # Should have overwritten
        analyzer = EmotionAnalyzerFactory.create("llm_tag_analyzer")
        assert isinstance(analyzer, MockAnalyzer)
        # Restore
        EmotionAnalyzerFactory._analyzers["llm_tag_analyzer"] = StandaloneLLMTagAnalyzer


# ============================================================
# TimelineStrategyFactory
# ============================================================

class TestTimelineStrategyFactory:
    """TimelineStrategyFactory create / register / list."""

    def test_create_position_based(self):
        """Create position_based strategy."""
        strategy = TimelineStrategyFactory.create("position_based")
        assert isinstance(strategy, PositionBasedStrategy)

    def test_create_duration_based(self):
        """Create duration_based strategy."""
        strategy = TimelineStrategyFactory.create("duration_based")
        assert isinstance(strategy, DurationBasedStrategy)

    def test_create_intensity_based(self):
        """Create intensity_based strategy."""
        strategy = TimelineStrategyFactory.create("intensity_based")
        assert isinstance(strategy, IntensityBasedStrategy)

    def test_create_with_config(self):
        """Create strategy with config."""
        strategy = TimelineStrategyFactory.create(
            "position_based",
            config={"enable_smoothing": False}
        )
        assert isinstance(strategy, PositionBasedStrategy)
        assert strategy._enable_smoothing is False

    def test_create_unknown_strategy_raises(self):
        """Unknown strategy name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            TimelineStrategyFactory.create("nonexistent_strategy")

    def test_list_all_contains_builtins(self):
        """list_all should include built-in strategies."""
        strategies = TimelineStrategyFactory.list_all()
        assert "position_based" in strategies
        assert "duration_based" in strategies
        assert "intensity_based" in strategies

    def test_is_registered_true(self):
        """is_registered should return True for known strategies."""
        assert TimelineStrategyFactory.is_registered("position_based") is True

    def test_is_registered_false(self):
        """is_registered should return False for unknown strategies."""
        assert TimelineStrategyFactory.is_registered("unknown") is False

    def test_register_new_strategy(self):
        """Register a new custom strategy."""
        class MockStrategy(ITimelineStrategy):
            def calculate(self, emotions, text, audio_duration, config=None, **kwargs):
                return []
            @property
            def name(self):
                return "mock_strategy"

        TimelineStrategyFactory.register("mock_test_strat", MockStrategy)
        try:
            assert TimelineStrategyFactory.is_registered("mock_test_strat") is True
            strategy = TimelineStrategyFactory.create("mock_test_strat")
            assert isinstance(strategy, MockStrategy)
        finally:
            TimelineStrategyFactory._strategies.pop("mock_test_strat", None)

    def test_register_non_interface_class_raises(self):
        """Registering a class that doesn't implement ITimelineStrategy should raise."""
        class NotAStrategy:
            pass

        with pytest.raises(ValueError, match="must implement ITimelineStrategy"):
            TimelineStrategyFactory.register("invalid_strat", NotAStrategy)

    def test_register_overwrite_warning(self):
        """Overwriting an existing strategy should work."""
        class MockStrategy(ITimelineStrategy):
            def calculate(self, emotions, text, audio_duration, config=None, **kwargs):
                return []
            @property
            def name(self):
                return "mock_strat2"

        TimelineStrategyFactory.register("position_based", MockStrategy)
        strategy = TimelineStrategyFactory.create("position_based")
        assert isinstance(strategy, MockStrategy)
        # Restore
        TimelineStrategyFactory._strategies["position_based"] = PositionBasedStrategy


# ============================================================
# Convenience functions
# ============================================================

class TestConvenienceFunctions:
    """create_emotion_analyzer and create_timeline_strategy."""

    def test_create_emotion_analyzer(self):
        """Convenience function should delegate to factory."""
        analyzer = create_emotion_analyzer("llm_tag_analyzer")
        assert isinstance(analyzer, StandaloneLLMTagAnalyzer)

    def test_create_emotion_analyzer_with_config(self):
        """Convenience function should pass config."""
        analyzer = create_emotion_analyzer(
            "keyword_analyzer",
            config={"confidence_mode": "count"}
        )
        assert analyzer._confidence_mode == "count"

    def test_create_timeline_strategy(self):
        """Convenience function should delegate to factory."""
        strategy = create_timeline_strategy("position_based")
        assert isinstance(strategy, PositionBasedStrategy)

    def test_create_timeline_strategy_with_config(self):
        """Convenience function should pass config."""
        strategy = create_timeline_strategy(
            "duration_based",
            config={"min_emotion_duration": 1.0}
        )
        assert strategy._min_emotion_duration == 1.0
