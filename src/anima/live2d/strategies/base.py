"""
时间轴策略接口和基础数据结构

定义了情绪时间轴计算策略的接口。
采用策略模式，支持不同的时间分配算法。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class TimelineSegment:
    """
    时间轴片段

    表示在特定时间段内的情绪状态。
    多个片段组合成完整的时间轴。

    Attributes:
        emotion: 情绪名称（如 "happy", "sad"）
        start_time: 开始时间（秒）
        end_time: 结束时间（秒）
        intensity: 情绪强度 (0.0 - 1.0，默认 1.0)

    Example:
        >>> segment = TimelineSegment("happy", 0.0, 2.5, intensity=0.8)
        >>> segment.to_dict()
        {'emotion': 'happy', 'time': 0.0, 'duration': 2.5}
        >>> segment.duration
        2.5
    """
    emotion: str
    start_time: float
    end_time: float
    intensity: float = 1.0

    @property
    def duration(self) -> float:
        """计算片段时长"""
        return self.end_time - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典（用于 WebSocket 消息）

        Returns:
            Dict[str, Any]: 前端可用的字典格式（包含 intensity）
        """
        return {
            "emotion": self.emotion,
            "time": self.start_time,
            "duration": self.duration,
            "intensity": self.intensity
        }

    def to_frontend_format(self) -> Dict[str, Any]:
        """
        转换为前端格式（兼容 audio_with_expression 事件）

        Returns:
            Dict[str, Any]: 包含 emotion, time, duration, intensity 的字典
        """
        return {
            "emotion": self.emotion,
            "time": self.start_time,
            "duration": self.duration,
            "intensity": self.intensity
        }

    def __repr__(self) -> str:
        """字符串表示"""
        return (f"TimelineSegment(emotion={self.emotion}, "
                f"start={self.start_time:.2f}s, "
                f"end={self.end_time:.2f}s, "
                f"intensity={self.intensity:.2f})")

    def contains_time(self, time: float) -> bool:
        """
        检查指定时间是否在片段内

        Args:
            time: 时间点（秒）

        Returns:
            bool: 如果时间在片段范围内返回 True
        """
        return self.start_time <= time < self.end_time

    def overlaps_with(self, other: 'TimelineSegment') -> bool:
        """
        检查是否与另一个片段重叠

        Args:
            other: 另一个时间轴片段

        Returns:
            bool: 如果两个片段有重叠返回 True
        """
        return not (self.end_time <= other.start_time or
                   self.start_time >= other.end_time)


@dataclass
class TimelineConfig:
    """
    时间轴配置参数

    用于配置时间轴计算的行为。

    Attributes:
        default_emotion: 默认情绪（当没有情绪时使用）
        min_segment_duration: 最小片段时长（秒）
        transition_duration: 过渡时长（秒）
        enable_smoothing: 是否启用平滑过渡
    """
    default_emotion: str = "neutral"
    min_segment_duration: float = 0.1
    transition_duration: float = 0.3
    enable_smoothing: bool = True

    def validate(self) -> bool:
        """验证配置参数"""
        return (
            self.min_segment_duration >= 0
            and self.transition_duration >= 0
            and len(self.default_emotion) > 0
        )


class ITimelineStrategy(ABC):
    """
    时间轴计算策略接口

    定义如何将情绪映射到时间轴。
    不同策略可以实现不同的时间分配算法。

    设计模式:
    - Strategy Pattern: 不同的时间轴计算策略
    - 可扩展: 轻松添加新的计算策略

    使用示例:
        >>> strategy = PositionBasedStrategy()
        >>> segments = strategy.calculate(
        ...     emotions=["happy", "neutral"],
        ...     text="Hello world",
        ...     audio_duration=5.0
        ... )
        >>> print(segments)
        [TimelineSegment(happy, 0.0, 2.5, 1.0), TimelineSegment(neutral, 2.5, 5.0, 1.0)]

    扩展示例:
        >>> class MyStrategy(ITimelineStrategy):
        ...     def calculate(self, emotions, text, audio_duration, **kwargs):
        ...         # 自定义时间分配逻辑
        ...         return [TimelineSegment(emotion, 0.0, audio_duration)]
        ...
        >>> from anima.live2d.factory import TimelineStrategyFactory
        >>> TimelineStrategyFactory.register("my_strategy", MyStrategy)
    """

    @abstractmethod
    def calculate(
        self,
        emotions: List[str],
        text: str,
        audio_duration: float,
        config: TimelineConfig = None,
        **kwargs
    ) -> List[TimelineSegment]:
        """
        计算情绪时间轴

        这是核心方法，所有策略必须实现。

        Args:
            emotions: 情绪列表（由 IEmotionAnalyzer 提取）
            text: 文本内容（用于语义分析）
            audio_duration: 音频时长（秒）
            config: 可选的配置参数
            **kwargs: 额外参数（用于未来扩展）

        Returns:
            List[TimelineSegment]: 时间轴片段列表
                - 片段按时间排序
                - 片段应该覆盖整个音频时长
                - 片段之间可以有间隙或重叠

        Raises:
            NotImplementedError: 子类必须实现
            ValueError: 参数无效

        Example:
            >>> strategy.calculate(
            ...     emotions=["happy", "neutral"],
            ...     text="Hello world",
            ...     audio_duration=10.0
            ... )
            [
                TimelineSegment(emotion="happy", start_time=0.0, end_time=5.0),
                TimelineSegment(emotion="neutral", start_time=5.0, end_time=10.0)
            ]
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        策略名称（唯一标识符）

        用于工厂注册和配置引用。
        必须是全局唯一的字符串。

        Returns:
            str: 策略名称

        Example:
            >>> strategy.name
            'position_based'
        """
        pass

    def validate_input(
        self,
        emotions: List[str],
        text: str,
        audio_duration: float
    ) -> bool:
        """
        验证输入参数（可选方法）

        子类可以覆盖此方法以添加自定义验证。

        Args:
            emotions: 情绪列表
            text: 文本内容
            audio_duration: 音频时长

        Returns:
            bool: 输入是否有效
        """
        return (
            audio_duration > 0
            and text is not None
            and len(text) >= 0
        )

    def ensure_full_coverage(
        self,
        segments: List[TimelineSegment],
        audio_duration: float,
        default_emotion: str = "neutral"
    ) -> List[TimelineSegment]:
        """
        确保时间轴覆盖整个音频时长

        如果时间轴有间隙，用默认情绪填充。
        这是辅助方法，子类可以使用。

        Args:
            segments: 原始时间轴片段
            audio_duration: 音频时长
            default_emotion: 默认情绪

        Returns:
            List[TimelineSegment]: 填充后的完整时间轴
        """
        if not segments:
            return [
                TimelineSegment(
                    emotion=default_emotion,
                    start_time=0.0,
                    end_time=audio_duration
                )
            ]

        # 按开始时间排序
        sorted_segments = sorted(segments, key=lambda s: s.start_time)

        # 检查是否有间隙
        result = []
        last_end = 0.0

        for segment in sorted_segments:
            # 如果有间隙，填充默认情绪
            if segment.start_time > last_end:
                result.append(TimelineSegment(
                    emotion=default_emotion,
                    start_time=last_end,
                    end_time=segment.start_time
                ))

            result.append(segment)
            last_end = max(last_end, segment.end_time)

        # 检查末尾是否覆盖
        if last_end < audio_duration:
            result.append(TimelineSegment(
                emotion=default_emotion,
                start_time=last_end,
                end_time=audio_duration
            ))

        return result

    def merge_adjacent_same_emotion(
        self,
        segments: List[TimelineSegment]
    ) -> List[TimelineSegment]:
        """
        合并相邻的相同情绪片段

        这是辅助方法，子类可以使用。
        减少片段数量，提高性能。

        Args:
            segments: 原始时间轴片段

        Returns:
            List[TimelineSegment]: 合并后的时间轴
        """
        if not segments:
            return []

        # 按时间排序
        sorted_segments = sorted(segments, key=lambda s: s.start_time)

        result = []
        current = sorted_segments[0]

        for next_seg in sorted_segments[1:]:
            # 如果情绪相同且有重叠或相邻，合并
            if (next_seg.emotion == current.emotion and
                next_seg.start_time <= current.end_time):
                current = TimelineSegment(
                    emotion=current.emotion,
                    start_time=current.start_time,
                    end_time=max(current.end_time, next_seg.end_time),
                    intensity=max(current.intensity, next_seg.intensity)
                )
            else:
                result.append(current)
                current = next_seg

        result.append(current)
        return result
