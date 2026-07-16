"""
Factory Module

Provides factory methods for emotion analyzers and timeline strategies.
Supports dynamic registration and creation of components.
"""

from typing import Any

from loguru import logger

from .analyzers.base import IEmotionAnalyzer
from .analyzers.keyword import KeywordAnalyzer
from .analyzers.llm_tag import StandaloneLLMTagAnalyzer
from .strategies.base import ITimelineStrategy
from .strategies.duration import DurationBasedStrategy
from .strategies.intensity import IntensityBasedStrategy
from .strategies.position import PositionBasedStrategy


class EmotionAnalyzerFactory:
    """
    Emotion Analyzer Factory

    Responsible for creating and managing emotion analyzer instances.
    Supports dynamic registration of custom analyzers.

    Design Patterns:
    - Factory Pattern: Creates objects without specifying concrete classes
    - Registry Pattern: Maintains a list of available analyzers

    Usage Examples:
        >>> # Use built-in analyzer
        >>> analyzer = EmotionAnalyzerFactory.create(
        ...     name="llm_tag_analyzer",
        ...     config={"valid_emotions": ["happy", "sad"]}
        ... )

        >>> # Register custom analyzer
        >>> class MyAnalyzer(IEmotionAnalyzer):
        ...     pass
        >>> EmotionAnalyzerFactory.register("my_analyzer", MyAnalyzer)
        >>> analyzer = EmotionAnalyzerFactory.create("my_analyzer", {})
    """

    # Built-in analyzer registry
    _analyzers: dict[str, type[IEmotionAnalyzer]] = {
        "llm_tag_analyzer": StandaloneLLMTagAnalyzer,  # Uses standalone implementation
        "keyword_analyzer": KeywordAnalyzer,
    }

    @classmethod
    def register(cls, name: str, analyzer_class: type[IEmotionAnalyzer]) -> None:
        """
        Register a custom analyzer

        Args:
            name: Analyzer name (unique identifier)
            analyzer_class: Analyzer class (must implement IEmotionAnalyzer)

        Raises:
            ValueError: Name already exists or class does not implement the interface

        Example:
            >>> class MyAnalyzer(IEmotionAnalyzer):
            ...     def extract(self, text, context=None): ...
            ...     @property
            ...     def name(self): return "my_analyzer"
            >>> EmotionAnalyzerFactory.register("my_analyzer", MyAnalyzer)
        """
        if name in cls._analyzers:
            logger.warning(
                f"[EmotionAnalyzerFactory] Analyzer '{name}' already exists, will be overwritten"
            )

        # Validate the class implements the interface
        if not issubclass(analyzer_class, IEmotionAnalyzer):
            raise ValueError(
                f"Analyzer class must implement IEmotionAnalyzer interface: {analyzer_class}"
            )

        cls._analyzers[name] = analyzer_class
        logger.info(
            f"[EmotionAnalyzerFactory] Registered analyzer: {name} ({analyzer_class.__name__})"
        )

    @classmethod
    def create(cls, name: str, config: dict[str, Any] | None = None) -> IEmotionAnalyzer:
        """
        Create an analyzer instance

        Args:
            name: Analyzer name
            config: Configuration parameters (passed to analyzer's __init__)

        Returns:
            IEmotionAnalyzer: Analyzer instance

        Raises:
            ValueError: Unknown analyzer name

        Example:
            >>> analyzer = EmotionAnalyzerFactory.create(
            ...     name="llm_tag_analyzer",
            ...     config={"valid_emotions": ["happy", "sad"]}
            ... )
        """
        analyzer_class = cls._analyzers.get(name)

        if not analyzer_class:
            available = ", ".join(cls._analyzers.keys())
            raise ValueError(f"Unknown analyzer: '{name}'. Available analyzers: {available}")

        # Create instance (pass configuration parameters)
        config = config or {}
        try:
            instance = analyzer_class(**config)
            logger.debug(f"[EmotionAnalyzerFactory] Created analyzer instance: {name}")
            return instance
        except Exception as e:
            logger.error(f"[EmotionAnalyzerFactory] Failed to create analyzer '{name}': {e}")
            raise

    @classmethod
    def list_all(cls) -> list[str]:
        """
        List all registered analyzers

        Returns:
            List[str]: List of analyzer names
        """
        return list(cls._analyzers.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """
        Check if an analyzer is registered

        Args:
            name: Analyzer name

        Returns:
            bool: Whether registered
        """
        return name in cls._analyzers


class TimelineStrategyFactory:
    """
    Timeline Strategy Factory

    Responsible for creating and managing timeline strategy instances.
    Supports dynamic registration of custom strategies.

    Design Patterns:
    - Factory Pattern: Creates strategy objects
    - Registry Pattern: Maintains a list of available strategies

    Usage Examples:
        >>> # Use built-in strategy
        >>> strategy = TimelineStrategyFactory.create("position_based")

        >>> # Register custom strategy
        >>> class MyStrategy(ITimelineStrategy):
        ...     def calculate(...): ...
        >>> TimelineStrategyFactory.register("my_strategy", MyStrategy)
        >>> strategy = TimelineStrategyFactory.create("my_strategy")
    """

    # Built-in strategy registry
    _strategies: dict[str, type[ITimelineStrategy]] = {
        "position_based": PositionBasedStrategy,
        "duration_based": DurationBasedStrategy,
        "intensity_based": IntensityBasedStrategy,
    }

    @classmethod
    def register(cls, name: str, strategy_class: type[ITimelineStrategy]) -> None:
        """
        Register a custom strategy

        Args:
            name: Strategy name (unique identifier)
            strategy_class: Strategy class (must implement ITimelineStrategy)

        Raises:
            ValueError: Name already exists or class does not implement the interface

        Example:
            >>> class MyStrategy(ITimelineStrategy):
            ...     def calculate(self, emotions, text, audio_duration, **kwargs):
            ...         return []
            ...     @property
            ...     def name(self): return "my_strategy"
            >>> TimelineStrategyFactory.register("my_strategy", MyStrategy)
        """
        if name in cls._strategies:
            logger.warning(
                f"[TimelineStrategyFactory] Strategy '{name}' already exists, will be overwritten"
            )

        # Validate the class implements the interface
        if not issubclass(strategy_class, ITimelineStrategy):
            raise ValueError(
                f"Strategy class must implement ITimelineStrategy interface: {strategy_class}"
            )

        cls._strategies[name] = strategy_class
        logger.info(
            f"[TimelineStrategyFactory] Registered strategy: {name} ({strategy_class.__name__})"
        )

    @classmethod
    def create(cls, name: str, config: dict[str, Any] | None = None) -> ITimelineStrategy:
        """
        Create a strategy instance

        Args:
            name: Strategy name
            config: Configuration parameters (passed to strategy's __init__)

        Returns:
            ITimelineStrategy: Strategy instance

        Raises:
            ValueError: Unknown strategy name

        Example:
            >>> strategy = TimelineStrategyFactory.create(
            ...     name="position_based",
            ...     config={"enable_smoothing": True}
            ... )
        """
        strategy_class = cls._strategies.get(name)

        if not strategy_class:
            available = ", ".join(cls._strategies.keys())
            raise ValueError(f"Unknown strategy: '{name}'. Available strategies: {available}")

        # Create instance (pass configuration parameters)
        config = config or {}
        try:
            instance = strategy_class(**config)
            logger.debug(f"[TimelineStrategyFactory] Created strategy instance: {name}")
            return instance
        except Exception as e:
            logger.error(f"[TimelineStrategyFactory] Failed to create strategy '{name}': {e}")
            raise

    @classmethod
    def list_all(cls) -> list[str]:
        """
        List all registered strategies

        Returns:
            List[str]: List of strategy names
        """
        return list(cls._strategies.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """
        Check if a strategy is registered

        Args:
            name: Strategy name

        Returns:
            bool: Whether registered
        """
        return name in cls._strategies


# Convenience functions
def create_emotion_analyzer(name: str, config: dict[str, Any] | None = None) -> IEmotionAnalyzer:
    """
    Convenience function to create an emotion analyzer

    Args:
        name: Analyzer name
        config: Configuration parameters

    Returns:
        IEmotionAnalyzer: Analyzer instance
    """
    return EmotionAnalyzerFactory.create(name, config)


def create_timeline_strategy(name: str, config: dict[str, Any] | None = None) -> ITimelineStrategy:
    """
    Convenience function to create a timeline strategy

    Args:
        name: Strategy name
        config: Configuration parameters

    Returns:
        ITimelineStrategy: Strategy instance
    """
    return TimelineStrategyFactory.create(name, config)
