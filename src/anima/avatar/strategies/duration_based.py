"""
持续时间基础时间轴策略

根据情绪类型分配不同的持续时间。
某些情绪（如 sad）可能需要更长的时间表达。
"""

from typing import List, Optional, Dict, Any
from loguru import logger

from .base import ITimelineStrategy, TimelineSegment, TimelineConfig


class DurationBasedStrategy(ITimelineStrategy):
    """
    基于持续时间的时间轴策略

    根据情绪类型分配不同的持续时间。
    不同情绪有不同的权重，影响其持续时间。

    功能:
    - 不同情绪有不同的时间权重
    - 支持自定义情绪持续时间映射
    - 支持最小和最大持续时间限制
    - 支持平滑过渡和相同情绪合并

    Attributes:
        config: 时间轴配置
        duration_weights: 情绪持续时间权重映射
        min_emotion_duration: 单个情绪的最小时长
        max_emotion_duration: 单个情绪的最大时长

    Example:
        >>> strategy = DurationBasedStrategy()
        >>> segments = strategy.calculate(
        ...     emotions=["happy", "sad", "happy"],
        ...     text="I'm happy but sad then happy",
        ...     audio_duration=10.0
        ... )
        >>> # sad 会分配更长的时间
    """

    # 默认情绪持续时间权重（相对于其他情绪的倍数）
    DEFAULT_DURATION_WEIGHTS = {
        "happy": 1.0,        # 标准时长
        "sad": 1.5,          # 悲伤情绪持续时间更长
        "angry": 1.2,        # 愤怒情绪稍长
        "surprised": 0.8,    # 惊讶情绪较短
        "thinking": 1.3,     # 思考需要时间
        "neutral": 1.0,      # 中性情绪标准时长
        "listening": 1.0,    # 倾听状态
        "speaking": 1.0,     # 说话状态
    }

    def __init__(
        self,
        config: TimelineConfig = None,
        duration_weights: Optional[Dict[str, float]] = None,
        min_emotion_duration: float = 0.5,
        max_emotion_duration: float = 5.0,
        enable_smoothing: bool = True
    ):
        """
        初始化策略

        Args:
            config: 时间轴配置
            duration_weights: 自定义情绪持续时间权重
            min_emotion_duration: 单个情绪的最小时长（秒）
            max_emotion_duration: 单个情绪的最大时长（秒）
            enable_smoothing: 是否启用平滑过渡
        """
        self.config = config or TimelineConfig()
        self._duration_weights = duration_weights or self.DEFAULT_DURATION_WEIGHTS.copy()
        self._min_emotion_duration = min_emotion_duration
        self._max_emotion_duration = max_emotion_duration
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
            config: 可选的配置
            **kwargs: 额外参数

        Returns:
            List[TimelineSegment]: 时间轴片段列表

        Raises:
            ValueError: 当输入参数无效时
        """
        timeline_config = config or self.config

        # 验证输入
        if not self.validate_input(emotions, text, audio_duration):
            raise ValueError(f"无效的输入参数")

        try:
            # 情况 1: 没有情绪
            if not emotions:
                logger.debug(f"[{self.name}] 没有情绪，使用默认情绪")
                return self._create_default_segment(
                    timeline_config.default_emotion,
                    audio_duration
                )

            # 情况 2: 根据权重分配时间
            segments = self._calculate_weighted_segments(
                emotions,
                audio_duration,
                timeline_config
            )

            # 可选：合并相邻相同情绪
            if self._enable_smoothing:
                segments = self.merge_adjacent_same_emotion(segments)

            # 确保完整覆盖
            segments = self.ensure_full_coverage(
                segments,
                audio_duration,
                timeline_config.default_emotion
            )

            # 应用最小时长过滤
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
            return self._create_default_segment(
                timeline_config.default_emotion,
                audio_duration
            )

    def _calculate_weighted_segments(
        self,
        emotions: List[str],
        audio_duration: float,
        config: TimelineConfig
    ) -> List[TimelineSegment]:
        """
        根据权重计算时间分配

        Args:
            emotions: 情绪列表
            audio_duration: 音频时长
            config: 时间轴配置

        Returns:
            List[TimelineSegment]: 时间轴片段列表
        """
        # 计算每个情绪的权重
        weights = []
        for emotion in emotions:
            weight = self._duration_weights.get(emotion, 1.0)
            weights.append(weight)

        # 计算总权重
        total_weight = sum(weights)

        # 如果总权重为0，平均分配
        if total_weight == 0:
            weight_sum = len(emotions)
        else:
            weight_sum = total_weight

        # 根据权重分配时间
        segments = []
        current_time = 0.0

        for i, (emotion, weight) in enumerate(zip(emotions, weights)):
            # 计算持续时间
            if total_weight == 0:
                duration = audio_duration / len(emotions)
            else:
                duration = (weight / total_weight) * audio_duration

            # 应用最小和最大限制
            duration = max(duration, self._min_emotion_duration)
            duration = min(duration, self._max_emotion_duration)

            start_time = current_time
            end_time = current_time + duration

            # 最后一个情绪延伸到音频结束
            if i == len(emotions) - 1:
                end_time = audio_duration

            segments.append(TimelineSegment(
                emotion=emotion,
                start_time=start_time,
                end_time=end_time,
                intensity=1.0
            ))

            current_time = end_time

            # 如果超过音频时长，停止
            if current_time >= audio_duration:
                break

        return segments

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

        # 如果所有片段都被过滤，保留最长的
        if not filtered and segments:
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
        return "duration_based"

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
        if not isinstance(audio_duration, (int, float)) or audio_duration <= 0:
            logger.warning(f"[{self.name}] 无效的音频时长: {audio_duration}")
            return False

        if not isinstance(text, str):
            logger.warning(f"[{self.name}] 无效的文本类型: {type(text)}")
            return False

        if emotions is None:
            logger.warning(f"[{self.name}] 情绪列表为 None")
            return False

        return True

    def set_duration_weight(self, emotion: str, weight: float) -> None:
        """
        设置情绪的持续时间权重

        Args:
            emotion: 情绪名称
            weight: 权重值（必须 > 0）
        """
        if weight <= 0:
            raise ValueError(f"权重必须大于 0: {weight}")

        self._duration_weights[emotion] = weight
        logger.debug(f"[{self.name}] 设置 {emotion} 的权重为 {weight}")

    def get_duration_weight(self, emotion: str) -> float:
        """
        获取情绪的持续时间权重

        Args:
            emotion: 情绪名称

        Returns:
            float: 权重值，如果不存在则返回 1.0
        """
        return self._duration_weights.get(emotion, 1.0)

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
        emotion_durations = {}

        for seg in segments:
            emotion_counts[seg.emotion] = emotion_counts.get(seg.emotion, 0) + 1
            emotion_durations[seg.emotion] = emotion_durations.get(seg.emotion, 0.0) + seg.duration

        return {
            "count": len(segments),
            "total_duration": sum(seg.duration for seg in segments),
            "emotions": list(emotion_counts.keys()),
            "emotion_counts": emotion_counts,
            "emotion_durations": emotion_durations,
            "average_duration": sum(seg.duration for seg in segments) / len(segments),
            "min_duration": min(seg.duration for seg in segments),
            "max_duration": max(seg.duration for seg in segments)
        }
