"""
工厂类模块

提供情绪分析器和时间轴策略的工厂方法。
支持动态注册和创建组件。
"""

from typing import Dict, Type, Optional, Any
from loguru import logger

from .analyzers.base import IEmotionAnalyzer
from .analyzers.llm_tag_analyzer import LLMTagAnalyzer
from .analyzers.keyword_analyzer import KeywordAnalyzer
from .strategies.base import ITimelineStrategy, TimelineConfig
from .strategies.position_based import PositionBasedStrategy
from .strategies.duration_based import DurationBasedStrategy
from .strategies.intensity_based import IntensityBasedStrategy


class EmotionAnalyzerFactory:
    """
    情绪分析器工厂

    负责创建和管理情绪分析器实例。
    支持动态注册自定义分析器。

    设计模式:
    - Factory Pattern: 创建对象而不指定具体类
    - Registry Pattern: 维护可用的分析器列表

    使用示例:
        >>> # 使用内置分析器
        >>> analyzer = EmotionAnalyzerFactory.create(
        ...     name="llm_tag_analyzer",
        ...     config={"valid_emotions": ["happy", "sad"]}
        ... )

        >>> # 注册自定义分析器
        >>> class MyAnalyzer(IEmotionAnalyzer):
        ...     pass
        >>> EmotionAnalyzerFactory.register("my_analyzer", MyAnalyzer)
        >>> analyzer = EmotionAnalyzerFactory.create("my_analyzer", {})
    """

    # 内置分析器注册表
    _analyzers: Dict[str, Type[IEmotionAnalyzer]] = {
        "llm_tag_analyzer": LLMTagAnalyzer,
        "keyword_analyzer": KeywordAnalyzer,
    }

    @classmethod
    def register(cls, name: str, analyzer_class: Type[IEmotionAnalyzer]) -> None:
        """
        注册自定义分析器

        Args:
            name: 分析器名称（唯一标识符）
            analyzer_class: 分析器类（必须实现 IEmotionAnalyzer）

        Raises:
            ValueError: 名称已存在或类未实现接口

        Example:
            >>> class MyAnalyzer(IEmotionAnalyzer):
            ...     def extract(self, text, context=None): ...
            ...     @property
            ...     def name(self): return "my_analyzer"
            >>> EmotionAnalyzerFactory.register("my_analyzer", MyAnalyzer)
        """
        if name in cls._analyzers:
            logger.warning(f"[EmotionAnalyzerFactory] 分析器 '{name}' 已存在，将被覆盖")

        # 验证类实现了接口
        if not issubclass(analyzer_class, IEmotionAnalyzer):
            raise ValueError(
                f"分析器类必须实现 IEmotionAnalyzer 接口: {analyzer_class}"
            )

        cls._analyzers[name] = analyzer_class
        logger.info(f"[EmotionAnalyzerFactory] 注册分析器: {name} ({analyzer_class.__name__})")

    @classmethod
    def create(cls, name: str, config: Optional[Dict[str, Any]] = None) -> IEmotionAnalyzer:
        """
        创建分析器实例

        Args:
            name: 分析器名称
            config: 配置参数（传递给分析器的 __init__）

        Returns:
            IEmotionAnalyzer: 分析器实例

        Raises:
            ValueError: 未知的分析器名称

        Example:
            >>> analyzer = EmotionAnalyzerFactory.create(
            ...     name="llm_tag_analyzer",
            ...     config={"valid_emotions": ["happy", "sad"]}
            ... )
        """
        analyzer_class = cls._analyzers.get(name)

        if not analyzer_class:
            available = ", ".join(cls._analyzers.keys())
            raise ValueError(
                f"未知的分析器: '{name}'。"
                f"可用的分析器: {available}"
            )

        # 创建实例（传递配置参数）
        config = config or {}
        try:
            instance = analyzer_class(**config)
            logger.debug(f"[EmotionAnalyzerFactory] 创建分析器实例: {name}")
            return instance
        except Exception as e:
            logger.error(f"[EmotionAnalyzerFactory] 创建分析器 '{name}' 失败: {e}")
            raise

    @classmethod
    def list_all(cls) -> list[str]:
        """
        列出所有已注册的分析器

        Returns:
            List[str]: 分析器名称列表
        """
        return list(cls._analyzers.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """
        检查分析器是否已注册

        Args:
            name: 分析器名称

        Returns:
            bool: 是否已注册
        """
        return name in cls._analyzers


class TimelineStrategyFactory:
    """
    时间轴策略工厂

    负责创建和管理时间轴策略实例。
    支持动态注册自定义策略。

    设计模式:
    - Factory Pattern: 创建策略对象
    - Registry Pattern: 维护可用的策略列表

    使用示例:
        >>> # 使用内置策略
        >>> strategy = TimelineStrategyFactory.create("position_based")

        >>> # 注册自定义策略
        >>> class MyStrategy(ITimelineStrategy):
        ...     def calculate(...): ...
        >>> TimelineStrategyFactory.register("my_strategy", MyStrategy)
        >>> strategy = TimelineStrategyFactory.create("my_strategy")
    """

    # 内置策略注册表
    _strategies: Dict[str, Type[ITimelineStrategy]] = {
        "position_based": PositionBasedStrategy,
        "duration_based": DurationBasedStrategy,
        "intensity_based": IntensityBasedStrategy,
    }

    @classmethod
    def register(cls, name: str, strategy_class: Type[ITimelineStrategy]) -> None:
        """
        注册自定义策略

        Args:
            name: 策略名称（唯一标识符）
            strategy_class: 策略类（必须实现 ITimelineStrategy）

        Raises:
            ValueError: 名称已存在或类未实现接口

        Example:
            >>> class MyStrategy(ITimelineStrategy):
            ...     def calculate(self, emotions, text, audio_duration, **kwargs):
            ...         return []
            ...     @property
            ...     def name(self): return "my_strategy"
            >>> TimelineStrategyFactory.register("my_strategy", MyStrategy)
        """
        if name in cls._strategies:
            logger.warning(f"[TimelineStrategyFactory] 策略 '{name}' 已存在，将被覆盖")

        # 验证类实现了接口
        if not issubclass(strategy_class, ITimelineStrategy):
            raise ValueError(
                f"策略类必须实现 ITimelineStrategy 接口: {strategy_class}"
            )

        cls._strategies[name] = strategy_class
        logger.info(f"[TimelineStrategyFactory] 注册策略: {name} ({strategy_class.__name__})")

    @classmethod
    def create(cls, name: str, config: Optional[Dict[str, Any]] = None) -> ITimelineStrategy:
        """
        创建策略实例

        Args:
            name: 策略名称
            config: 配置参数（传递给策略的 __init__）

        Returns:
            ITimelineStrategy: 策略实例

        Raises:
            ValueError: 未知的策略名称

        Example:
            >>> strategy = TimelineStrategyFactory.create(
            ...     name="position_based",
            ...     config={"enable_smoothing": True}
            ... )
        """
        strategy_class = cls._strategies.get(name)

        if not strategy_class:
            available = ", ".join(cls._strategies.keys())
            raise ValueError(
                f"未知的策略: '{name}'。"
                f"可用的策略: {available}"
            )

        # 创建实例（传递配置参数）
        config = config or {}
        try:
            instance = strategy_class(**config)
            logger.debug(f"[TimelineStrategyFactory] 创建策略实例: {name}")
            return instance
        except Exception as e:
            logger.error(f"[TimelineStrategyFactory] 创建策略 '{name}' 失败: {e}")
            raise

    @classmethod
    def list_all(cls) -> list[str]:
        """
        列出所有已注册的策略

        Returns:
            List[str]: 策略名称列表
        """
        return list(cls._strategies.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """
        检查策略是否已注册

        Args:
            name: 策略名称

        Returns:
            bool: 是否已注册
        """
        return name in cls._strategies


# 便捷函数
def create_emotion_analyzer(
    name: str,
    config: Optional[Dict[str, Any]] = None
) -> IEmotionAnalyzer:
    """
    创建情绪分析器的便捷函数

    Args:
        name: 分析器名称
        config: 配置参数

    Returns:
        IEmotionAnalyzer: 分析器实例
    """
    return EmotionAnalyzerFactory.create(name, config)


def create_timeline_strategy(
    name: str,
    config: Optional[Dict[str, Any]] = None
) -> ITimelineStrategy:
    """
    创建时间轴策略的便捷函数

    Args:
        name: 策略名称
        config: 配置参数

    Returns:
        ITimelineStrategy: 策略实例
    """
    return TimelineStrategyFactory.create(name, config)
