"""
表情时间轴计算器
根据表情标签在文本中的位置和音频时长，计算表情切换时间轴
"""

from dataclasses import dataclass
from typing import List, Optional
from loguru import logger

from .emotion_extractor import EmotionTag


@dataclass
class EmotionSegment:
    """表情时间轴片段"""
    emotion: str        # "happy", "sad", etc.
    start_time: float   # 开始时间（秒）
    end_time: float     # 结束时间（秒）
    duration: float     # 持续时间（秒）

    def __repr__(self) -> str:
        return f"EmotionSegment({self.emotion}, {self.start_time:.2f}s-{self.end_time:.2f}s)"


@dataclass
class EmotionTimeline:
    """表情时间轴"""
    segments: List[EmotionSegment]  # 表情片段列表
    total_duration: float            # 总时长（秒）
    default_emotion: str = "neutral"  # 默认表情

    def __repr__(self) -> str:
        return f"EmotionTimeline({len(self.segments)} segments, {self.total_duration:.2f}s)"

    def get_emotion_at_time(self, time: float) -> str:
        """
        获取指定时间的表情

        Args:
            time: 时间点（秒）

        Returns:
            表情名称
        """
        # 查找包含该时间的片段
        for segment in self.segments:
            if segment.start_time <= time < segment.end_time:
                return segment.emotion

        # 如果超出范围，返回最后一个表情或默认表情
        if self.segments and time >= self.segments[-1].end_time:
            return self.segments[-1].emotion

        return self.default_emotion


class EmotionTimelineCalculator:
    """
    表情时间轴计算器

    策略：
    1. 根据表情标签在文本中的位置分配时间
    2. 文本前的区域使用默认表情
    3. 相邻的表情标签之间平均分配时间

    示例:
        text: "Hello [happy] world [sad] goodbye"
        audio_duration: 10s
        text_length: 25 (移除标签后)

        Timeline:
        - neutral: 0.0s - 2.4s (24% 位置)
        - happy: 2.4s - 5.6s (24% - 56% 位置)
        - sad: 5.6s - 10.0s (56% - 100% 位置)
    """

    def __init__(self, default_emotion: str = "neutral"):
        """
        初始化时间轴计算器

        Args:
            default_emotion: 默认表情（当没有表情时使用）
        """
        self.default_emotion = default_emotion

    def calculate(
        self,
        emotions: List[EmotionTag],
        cleaned_text: str,
        audio_duration: float
    ) -> EmotionTimeline:
        """
        计算表情时间轴

        Args:
            emotions: 表情标签列表
            cleaned_text: 清理后的文本（不含表情标签）
            audio_duration: 音频总时长（秒）

        Returns:
            EmotionTimeline: 表情时间轴
        """
        if audio_duration <= 0:
            logger.warning(f"[EmotionTimelineCalculator] 音频时长无效: {audio_duration}")
            return EmotionTimeline(
                segments=[],
                total_duration=0.0,
                default_emotion=self.default_emotion
            )

        # 没有表情标签：使用默认表情
        if not emotions:
            segment = EmotionSegment(
                emotion=self.default_emotion,
                start_time=0.0,
                end_time=audio_duration,
                duration=audio_duration
            )
            return EmotionTimeline(
                segments=[segment],
                total_duration=audio_duration,
                default_emotion=self.default_emotion
            )

        # 按位置排序
        emotions = sorted(emotions, key=lambda e: e.position)

        # 计算文本长度（用于位置归一化）
        text_length = len(cleaned_text)
        if text_length == 0:
            text_length = 1  # 避免除零

        # 构建时间轴片段
        segments = []
        last_time = 0.0

        for i, emotion_tag in enumerate(emotions):
            # 计算该表情标签的相对位置 (0.0 - 1.0)
            relative_pos = min(emotion_tag.position / text_length, 1.0)

            # 计算该表情的开始时间
            start_time = relative_pos * audio_duration

            # 计算该表情的结束时间
            # 如果是最后一个表情，则持续到音频结束
            if i == len(emotions) - 1:
                end_time = audio_duration
            else:
                # 下一个表情的位置
                next_relative_pos = min(emotions[i + 1].position / text_length, 1.0)
                # 使用中间点作为切换时间
                end_time = ((relative_pos + next_relative_pos) / 2) * audio_duration

            duration = end_time - start_time

            # 如果时间间隔太短（< 0.1s），跳过
            if duration < 0.1:
                logger.debug(f"[EmotionTimelineCalculator] 跳过太短的表情: {emotion_tag.emotion} ({duration:.3f}s)")
                continue

            # 添加默认表情片段（如果有间隔）
            if start_time > last_time:
                neutral_duration = start_time - last_time
                if neutral_duration >= 0.1:  # 至少 0.1s
                    segments.append(EmotionSegment(
                        emotion=self.default_emotion,
                        start_time=last_time,
                        end_time=start_time,
                        duration=neutral_duration
                    ))

            # 添加表情片段
            segments.append(EmotionSegment(
                emotion=emotion_tag.emotion,
                start_time=start_time,
                end_time=end_time,
                duration=duration
            ))

            last_time = end_time

        # 验证时间轴覆盖完整
        if segments:
            # 确保最后一片段延伸到音频结束
            if segments[-1].end_time < audio_duration:
                segments[-1].end_time = audio_duration
                segments[-1].duration = audio_duration - segments[-1].start_time

        logger.debug(
            f"[EmotionTimelineCalculator] 计算时间轴: {len(segments)} 个片段, "
            f"总时长 {audio_duration:.2f}s"
        )

        return EmotionTimeline(
            segments=segments,
            total_duration=audio_duration,
            default_emotion=self.default_emotion
        )
