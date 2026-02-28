"""
强度基础时间轴策略

根据情绪强度计算时间轴片段。
强度高的情绪会获得更多的时间和更高的强度值。
"""

from typing import List, Optional, Dict, Any
from loguru import logger

from .base import ITimelineStrategy, TimelineSegment, TimelineConfig


class IntensityBasedStrategy(ITimelineStrategy):
    """
    基于强度的时间轴策略

    根据情绪强度分配时间和设置强度值。
    不同情绪有不同的默认强度，也可以自定义。

    功能:
    - 不同情绪有不同的强度值
    - 强度高的情绪获得更多时间
    - 支持自定义情绪强度映射
    - 支持强度阈值过滤
    - 支持平滑过渡

    Attributes:
        config: 时间轴配置
        emotion_intensities: 情绪强度映射 (0.0 - 1.0)
        min_intensity: 最小强度阈值（低于此值的情绪会被过滤）
        intensity_factor: 强度对时间分配的影响因子（0.0 - 1.0）

    Example:
        >>> strategy = IntensityBasedStrategy(
        ...     intensity_factor=0.8
        ... )
        >>> segments = strategy.calculate(
        ...     emotions=["happy", "sad", "surprised"],
        ...     text="I'm happy sad and surprised",
        ...     audio_duration=9.0
        ... )
        >>> # 高强度情绪（如 surprised）会获得更多时间
    """

    # 默认情绪强度值（0.0 - 1.0）
    DEFAULT_EMOTION_INTENSITIES = {
        "happy": 0.8,          # 高强度
        "sad": 0.6,            # 中等强度
        "angry": 0.9,          # 很高强度
        "surprised": 0.95,     # 极高强度（时间短但强烈）
        "thinking": 0.4,       # 较低强度
        "neutral": 0.3,        # 低强度
        "listening": 0.3,      # 低强度
        "speaking": 0.7,       # 中高强度
    }

    def __init__(
        self,
        config: TimelineConfig = None,
        emotion_intensities: Optional[Dict[str, float]] = None,
        min_intensity: float = 0.2,
        intensity_factor: float = 0.5,
        enable_smoothing: bool = True
    ):
        """
        初始化策略

        Args:
            config: 时间轴配置
            emotion_intensities: 自定义情绪强度映射
            min_intensity: 最小强度阈值（低于此值的情绪会被过滤）
            intensity_factor: 强度对时间分配的影响因子（0.0 = 无影响，1.0 = 完全影响）
            enable_smoothing: 是否启用平滑过渡
        """
        self.config = config or TimelineConfig()
        self._emotion_intensities = emotion_intensities or self.DEFAULT_EMOTION_INTENSITIES.copy()
        self._min_intensity = min_intensity
        self._intensity_factor = max(0.0, min(1.0, intensity_factor))
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

            # 情况 2: 根据强度分配时间和强度值
            segments = self._calculate_intensity_segments(
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

            # 应用最小强度过滤
            segments = self._filter_low_intensity_segments(
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

    def _calculate_intensity_segments(
        self,
        emotions: List[str],
        audio_duration: float,
        config: TimelineConfig
    ) -> List[TimelineSegment]:
        """
        根据强度计算时间分配和强度值

        Args:
            emotions: 情绪列表
            audio_duration: 音频时长
            config: 时间轴配置

        Returns:
            List[TimelineSegment]: 时间轴片段列表
        """
        # 获取每个情绪的强度
        intensities = []
        for emotion in emotions:
            intensity = self._emotion_intensities.get(emotion, 0.5)
            intensities.append(intensity)

        # 过滤低强度情绪
        filtered_emotions = []
        filtered_intensities = []
        for emotion, intensity in zip(emotions, intensities):
            if intensity >= self._min_intensity:
                filtered_emotions.append(emotion)
                filtered_intensities.append(intensity)
            else:
                logger.debug(
                    f"[{self.name}] 过滤低强度情绪: {emotion} ({intensity:.2f})"
                )

        # 如果所有情绪都被过滤，使用默认情绪
        if not filtered_emotions:
            return self._create_default_segment(config.default_emotion, audio_duration)

        # 计算加权强度（考虑 intensity_factor）
        # intensity_factor = 0.0 时，所有情绪平均分配时间
        # intensity_factor = 1.0 时，完全按强度比例分配时间
        if self._intensity_factor == 0.0:
            # 平均分配
            weights = [1.0] * len(filtered_emotions)
        else:
            # 按强度分配，但考虑 intensity_factor
            base_weights = [1.0] * len(filtered_emotions)
            intensity_weights = filtered_intensities
            weights = [
                (1 - self._intensity_factor) * base + self._intensity_factor * intensity
                for base, intensity in zip(base_weights, intensity_weights)
            ]

        total_weight = sum(weights)

        # 根据权重分配时间
        segments = []
        current_time = 0.0

        for i, (emotion, intensity, weight) in enumerate(zip(
            filtered_emotions,
            filtered_intensities,
            weights
        )):
            # 计算持续时间
            if total_weight == 0:
                duration = audio_duration / len(filtered_emotions)
            else:
                duration = (weight / total_weight) * audio_duration

            start_time = current_time
            end_time = current_time + duration

            # 最后一个情绪延伸到音频结束
            if i == len(filtered_emotions) - 1:
                end_time = audio_duration

            segments.append(TimelineSegment(
                emotion=emotion,
                start_time=start_time,
                end_time=end_time,
                intensity=intensity  # 使用情绪的强度值
            ))

            current_time = end_time

            if current_time >= audio_duration:
                break

        return segments

    def _filter_low_intensity_segments(
        self,
        segments: List[TimelineSegment],
        min_duration: float
    ) -> List[TimelineSegment]:
        """
        过滤掉强度低或时间短的时间段

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

        if not filtered and segments:
            # 保留强度最高的片段
            highest = max(segments, key=lambda s: s.intensity)
            return [highest]

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
                intensity=0.5  # 默认中等强度
            )
        ]

    @property
    def name(self) -> str:
        """策略名称"""
        return "intensity_based"

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

    def set_emotion_intensity(self, emotion: str, intensity: float) -> None:
        """
        设置情绪的强度值

        Args:
            emotion: 情绪名称
            intensity: 强度值（0.0 - 1.0）
        """
        if not 0.0 <= intensity <= 1.0:
            raise ValueError(f"强度值必须在 0.0 - 1.0 之间: {intensity}")

        self._emotion_intensities[emotion] = intensity
        logger.debug(f"[{self.name}] 设置 {emotion} 的强度为 {intensity}")

    def get_emotion_intensity(self, emotion: str) -> float:
        """
        获取情绪的强度值

        Args:
            emotion: 情绪名称

        Returns:
            float: 强度值，如果不存在则返回 0.5
        """
        return self._emotion_intensities.get(emotion, 0.5)

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
                "average_duration": 0.0,
                "average_intensity": 0.0
            }

        emotion_counts = {}
        emotion_durations = {}
        emotion_intensities = {}

        for seg in segments:
            emotion_counts[seg.emotion] = emotion_counts.get(seg.emotion, 0) + 1
            emotion_durations[seg.emotion] = emotion_durations.get(seg.emotion, 0.0) + seg.duration

            # 记录强度（取平均值）
            if seg.emotion not in emotion_intensities:
                emotion_intensities[seg.emotion] = []
            emotion_intensities[seg.emotion].append(seg.intensity)

        # 计算平均强度
        avg_intensities = {
            emotion: sum(intensities) / len(intensities)
            for emotion, intensities in emotion_intensities.items()
        }

        return {
            "count": len(segments),
            "total_duration": sum(seg.duration for seg in segments),
            "emotions": list(emotion_counts.keys()),
            "emotion_counts": emotion_counts,
            "emotion_durations": emotion_durations,
            "average_intensity": sum(seg.intensity for seg in segments) / len(segments),
            "emotion_intensities": avg_intensities,
            "average_duration": sum(seg.duration for seg in segments) / len(segments),
            "min_duration": min(seg.duration for seg in segments),
            "max_duration": max(seg.duration for seg in segments)
        }
