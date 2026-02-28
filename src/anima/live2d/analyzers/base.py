"""
情绪分析器接口和基础数据结构

定义了所有情绪分析器必须实现的接口。
采用策略模式和插件架构，支持动态扩展。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class EmotionData:
    """
    情绪数据（统一格式）

    所有情绪分析器必须返回此格式。
    包含情绪信息、置信度、时间轴和元数据。

    Attributes:
        primary: 主要情绪（如 "happy", "sad"）
        confidence: 置信度 (0.0 - 1.0)
        timeline: 情绪时间轴片段列表
        metadata: 额外信息（用于调试和扩展）

    Example:
        >>> data = EmotionData(
        ...     primary="happy",
        ...     confidence=0.9,
        ...     timeline=[{"emotion": "happy", "position": 6}],
        ...     metadata={"source": "llm_tag"}
        ... )
        >>> data.to_dict()
        {
            'primary': 'happy',
            'confidence': 0.9,
            'timeline': [{'emotion': 'happy', 'position': 6}],
            'metadata': {'source': 'llm_tag'}
        }
    """
    primary: str
    confidence: float
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典（用于序列化和日志）

        Returns:
            Dict[str, Any]: 包含所有字段的字典
        """
        return {
            "primary": self.primary,
            "confidence": self.confidence,
            "timeline": self.timeline,
            "metadata": self.metadata
        }

    def __repr__(self) -> str:
        """字符串表示"""
        return (f"EmotionData(primary={self.primary}, "
                f"confidence={self.confidence:.2f}, "
                f"timeline_items={len(self.timeline)})")


class IEmotionAnalyzer(ABC):
    """
    情绪分析器接口

    所有情绪分析器必须实现此接口。
    插件系统通过此接口实现多态性。

    设计模式:
    - Strategy Pattern: 不同的情绪分析策略
    - Plugin Pattern: 可动态注册的分析器

    使用示例:
        >>> from anima.live2d.analyzers import LLMTagAnalyzer
        >>> analyzer = LLMTagAnalyzer(valid_emotions=["happy", "sad"])
        >>> result = analyzer.extract("Hello [happy] world!")
        >>> print(result.primary)
        'happy'

    扩展示例:
        >>> from anima.live2d.analyzers.base import IEmotionAnalyzer
        >>> class MyAnalyzer(IEmotionAnalyzer):
        ...     def extract(self, text, context=None):
        ...         # 自定义分析逻辑
        ...         return EmotionData(primary="neutral", confidence=0.5)
        ...
        >>> from anima.live2d.factory import EmotionAnalyzerFactory
        >>> EmotionAnalyzerFactory.register("my_analyzer", MyAnalyzer)
    """

    @abstractmethod
    def extract(self, text: str, context: Optional[Dict[str, Any]] = None) -> EmotionData:
        """
        从文本中提取情绪信息

        这是核心方法，所有分析器必须实现。

        Args:
            text: 待分析的文本
            context: 可选的上下文信息，包含:
                - conversation_history: 对话历史
                - user_input: 用户输入
                - user_state: 用户状态
                - custom: 自定义上下文

        Returns:
            EmotionData: 提取的情绪数据，包含:
                - primary: 主要情绪
                - confidence: 置信度 (0.0 - 1.0)
                - timeline: 情绪时间轴
                - metadata: 调试信息

        Raises:
            NotImplementedError: 子类必须实现
            ValueError: 输入参数无效

        Example:
            >>> analyzer.extract("今天天气真好！")
            EmotionData(primary='happy', confidence=0.8, ...)
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        分析器名称（唯一标识符）

        用于工厂注册和配置引用。
        必须是全局唯一的字符串。

        Returns:
            str: 分析器名称

        Example:
            >>> analyzer.name
            'llm_tag_analyzer'
        """
        pass

    @property
    def priority(self) -> int:
        """
        优先级（数字越小优先级越高）

        当多个分析器同时使用时，优先级决定处理顺序。
        默认值为 100（中等优先级）。

        Returns:
            int: 优先级值（推荐范围: 1-100）

        Example:
            >>> # 高优先级分析器
            >>> @property
            >>> def priority(self) -> int:
            ...     return 1
        """
        return 100

    def validate_input(self, text: str) -> bool:
        """
        验证输入参数（可选方法）

        子类可以覆盖此方法以添加自定义验证逻辑。

        Args:
            text: 待验证的文本

        Returns:
            bool: 输入是否有效
        """
        return text is not None and len(text.strip()) > 0

    def get_supported_emotions(self) -> List[str]:
        """
        获取支持的情绪列表（可选方法）

        子类可以覆盖此方法以声明支持的情绪。

        Returns:
            List[str]: 支持的情绪列表
        """
        return []  # 空列表表示支持所有情绪
