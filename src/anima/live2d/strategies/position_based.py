"""
位置基础时间轴策略（增强版）

根据情绪标签在文本中的位置分配时间。
实现新的 ITimelineStrategy 接口，增强错误处理和功能。
"""

from typing import List, Optional, Dict, Any
from loguru import logger

from .base import ITimelineStrategy, TimelineSegment, TimelineConfig


class PositionBasedStrategy(ITimelineStrategy):
    """
    基于位置的时间轴策略

    根据情绪标签在文本中的位置平均分配时间。
    支持平滑过渡和自定义强度计算。

    功能:
    - 根据情绪列表平均分配时间
    - 支持相邻相同情绪合并
    - 支持过渡平滑（transition_duration）
    - 支持自定义强度计算
    - 完善的错误处理和验证

    Attributes:
        config: 时间轴配置参数
        enable_smoothing: 是否启用平滑过渡

    Example:
        >>> strategy = PositionBasedStrategy(
        ...     enable_smoothing=True,
        ...     transition_duration=0.5
        ... )
        >>> segments = strategy.calculate(
        ...     emotions=["happy", "neutral", "sad"],
        ...     text="Hello world",
        ...     audio_duration=6.0
        ... )
        >>> print(len(segments))
        3
    """

    def __init__(
        self,
        config: TimelineConfig = None,
        enable_smoothing: bool = True
    ):
        """
        初始化策略

        Args:
            config: 时间轴配置
            enable_smoothing: 是否启用平滑过渡（合并相邻相同情绪）
        """
        self.config = config or TimelineConfig()
        self._enable_smoothing = enable_smoothing

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

        Args:
            emotions: 情绪列表
            text: 文本内容
            audio_duration: 音频时长
            config: 可选的配置（覆盖实例配置）
            **kwargs: 额外参数（如 emotion_positions 情绪位置信息）

        Returns:
            List[TimelineSegment]: 时间轴片段列表

        Raises:
            ValueError: 当输入参数无效时
        """
        # 使用提供的配置或实例配置
        timeline_config = config or self.config

        # 验证输入
        if not self.validate_input(emotions, text, audio_duration):
            raise ValueError(f"无效的输入参数: emotions={emotions}, audio_duration={audio_duration}")

        try:
            # 情况 1: 没有情绪
            if not emotions:
                logger.debug(f"[{self.name}] 没有情绪，使用默认情绪")
                return self._create_default_segment(
                    timeline_config.default_emotion,
                    audio_duration
                )

            # 情况 2: 有情绪，平均分配时间
            segments = self._calculate_even_segments(
                emotions,
                audio_duration,
                timeline_config
            )

            # 可选：合并相邻相同情绪
            if self._enable_smoothing:
                segments = self.merge_adjacent_same_emotion(segments)

            # 确保完整覆盖音频时长
            segments = self.ensure_full_coverage(
                segments,
                audio_duration,
                timeline_config.default_emotion
            )

            # 应用最小片段时长过滤
            segments = self._filter_short_segments(
                segments,
                timeline_config.min_segment_duration
            )

            logger.debug(
                f"[{self.name}] 计算了 {len(segments)} 个时间轴片段, "
                f"总时长 {audio_duration:.2f}s"
            )

            return segments

        except Exception as e:
            logger.error(f"[{self.name}] 计算时间轴失败: {e}")
            # 返回默认时间轴
            return self._create_default_segment(
                timeline_config.default_emotion,
                audio_duration
            )

    def _calculate_even_segments(
        self,
        emotions: List[str],
        audio_duration: float,
        config: TimelineConfig
    ) -> List[TimelineSegment]:
        """
        计算平均分配的时间段

        Args:
            emotions: 情绪列表
            audio_duration: 音频时长
            config: 时间轴配置

        Returns:
            List[TimelineSegment]: 时间轴片段列表
        """
        segment_duration = audio_duration / len(emotions)
        segments = []

        for i, emotion in enumerate(emotions):
            start_time = i * segment_duration
            end_time = (i + 1) * segment_duration

            # 计算强度（可以扩展为基于情绪的强度）
            intensity = self._calculate_intensity(emotion, i, len(emotions))

            segments.append(TimelineSegment(
                emotion=emotion,
                start_time=start_time,
                end_time=end_time,
                intensity=intensity
            ))

        return segments

    def _calculate_intensity(
        self,
        emotion: str,
        index: int,
        total_emotions: int
    ) -> float:
        """
        计算情绪强度

        可以根据情绪类型、位置等因素计算强度。
        默认返回固定强度 1.0。

        Args:
            emotion: 情绪名称
            index: 情绪在列表中的索引
            total_emotions: 总情绪数

        Returns:
            float: 强度值 (0.0 - 1.0)
        """
        # 默认强度
        return 1.0

    def _filter_short_segments(
        self,
        segments: List[TimelineSegment],
        min_duration: float
    ) -> List[TimelineSegment]:
        """
        过滤掉太短的时间段

        Args:
            segments: 时间轴片段列表
            min_duration: 最小时长

        Returns:
            List[TimelineSegment]: 过滤后的片段列表
        """
        filtered = []
        for segment in segments:
            if segment.duration >= min_duration:
                filtered.append(segment)
            else:
                logger.debug(
                    f"[{self.name}] 跳过太短的情绪片段: "
                    f"{segment.emotion} ({segment.duration:.3f}s)"
                )

        # 如果所有片段都被过滤，返回第一个片段
        if not filtered and segments:
            # 保留最长的片段
            longest = max(segments, key=lambda s: s.duration)
            return [longest]

        return filtered

    def _create_default_segment(
        self,
        emotion: str,
        duration: float
    ) -> List[TimelineSegment]:
        """
        创建默认时间轴片段

        Args:
            emotion: 情绪名称
            duration: 时长

        Returns:
            List[TimelineSegment]: 包含单个片段的列表
        """
        return [
            TimelineSegment(
                emotion=emotion,
                start_time=0.0,
                end_time=duration,
                intensity=1.0
            )
        ]

    @property
    def name(self) -> str:
        """策略名称"""
        return "position_based"

    def validate_input(
        self,
        emotions: List[str],
        text: str,
        audio_duration: float
    ) -> bool:
        """
        验证输入参数

        Args:
            emotions: 情绪列表
            text: 文本内容
            audio_duration: 音频时长

        Returns:
            bool: 是否有效
        """
        # 检查音频时长
        if not isinstance(audio_duration, (int, float)) or audio_duration <= 0:
            logger.warning(f"[{self.name}] 无效的音频时长: {audio_duration}")
            return False

        # 检查文本
        if not isinstance(text, str):
            logger.warning(f"[{self.name}] 无效的文本类型: {type(text)}")
            return False

        # 检查情绪列表
        if emotions is None:
            logger.warning(f"[{self.name}] 情绪列表为 None")
            return False

        return True

    def get_segment_info(self, segments: List[TimelineSegment]) -> Dict[str, Any]:
        """
        获取时间轴片段的统计信息

        Args:
            segments: 时间轴片段列表

        Returns:
            Dict: 统计信息
        """
        if not segments:
            return {
                "count": 0,
                "total_duration": 0.0,
                "emotions": [],
                "average_duration": 0.0
            }

        emotion_counts = {}
        for seg in segments:
            emotion_counts[seg.emotion] = emotion_counts.get(seg.emotion, 0) + 1

        return {
            "count": len(segments),
            "total_duration": sum(seg.duration for seg in segments),
            "emotions": list(emotion_counts.keys()),
            "emotion_counts": emotion_counts,
            "average_duration": sum(seg.duration for seg in segments) / len(segments),
            "min_duration": min(seg.duration for seg in segments),
            "max_duration": max(seg.duration for seg in segments)
        }
