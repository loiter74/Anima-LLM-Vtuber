"""
表情提取器
从 LLM 响应文本中提取情感标签（如 [happy]）
"""

import re
from dataclasses import dataclass
from typing import List, Optional
from loguru import logger


@dataclass
class EmotionTag:
    """表情标签"""
    emotion: str       # "happy", "sad", etc.
    position: int      # Character position in original text
    duration: float = 0.0  # Duration (calculated later by timeline)

    def __repr__(self) -> str:
        return f"EmotionTag({self.emotion}, pos={self.position})"


@dataclass
class EmotionExtractionResult:
    """表情提取结果"""
    cleaned_text: str          # 移除表情标签后的文本
    emotions: List[EmotionTag]  # 提取的表情标签列表
    has_emotions: bool          # 是否包含表情

    def __repr__(self) -> str:
        return f"EmotionExtractionResult(emotions={len(self.emotions)}, cleaned_len={len(self.cleaned_text)})"


class EmotionExtractor:
    """
    表情提取器

    从文本中提取表情标签，并返回清理后的文本
    支持的表情格式: [happy], [sad], [angry] 等

    示例:
        Input: "Hello [happy] world! [sad] Goodbye."
        Output: EmotionExtractionResult(
            cleaned_text="Hello  world!  Goodbye.",
            emotions=[EmotionTag("happy", 6), EmotionTag("sad", 20)]
        )
    """

    # 匹配表情标签的正则: [emotion_name]
    EMOTION_PATTERN = re.compile(r'\[([a-zA-Z_]+)\]')

    def __init__(self, valid_emotions: Optional[List[str]] = None):
        """
        初始化表情提取器

        Args:
            valid_emotions: 有效的表情列表。如果为 None，则接受所有标签
        """
        self.valid_emotions = set(valid_emotions) if valid_emotions else None

    def extract(self, text: str) -> EmotionExtractionResult:
        """
        从文本中提取表情标签

        Args:
            text: 原始文本（可能包含表情标签）

        Returns:
            EmotionExtractionResult: 清理后的文本和提取的表情
        """
        if not text:
            return EmotionExtractionResult(
                cleaned_text="",
                emotions=[],
                has_emotions=False
            )

        emotions = []
        # 记录需要移除的片段
        segments_to_remove = []

        for match in self.EMOTION_PATTERN.finditer(text):
            emotion = match.group(1).lower()
            position = match.start()

            # 如果设置了有效表情列表，则验证
            if self.valid_emotions and emotion not in self.valid_emotions:
                logger.debug(f"[EmotionExtractor] 忽略无效表情: [{emotion}]")
                continue

            # 创建表情标签
            emotions.append(EmotionTag(emotion=emotion, position=position))
            segments_to_remove.append((match.start(), match.end()))

        # 清理文本：移除所有表情标签
        cleaned_text = self._remove_segments(text, segments_to_remove)

        logger.debug(f"[EmotionExtractor] 提取了 {len(emotions)} 个表情: {emotions}")

        return EmotionExtractionResult(
            cleaned_text=cleaned_text,
            emotions=emotions,
            has_emotions=len(emotions) > 0
        )

    def _remove_segments(self, text: str, segments: List[tuple]) -> str:
        """
        从文本中移除指定片段

        Args:
            text: 原始文本
            segments: 要移除的 (start, end) 位置列表

        Returns:
            清理后的文本
        """
        if not segments:
            return text

        # 按位置排序并从后往前移除（避免位置偏移）
        segments = sorted(segments, key=lambda x: x[0], reverse=True)

        result = text
        for start, end in segments:
            result = result[:start] + result[end:]

        return result

    def is_valid_emotion(self, emotion: str) -> bool:
        """
        检查表情是否有效

        Args:
            emotion: 表情名称

        Returns:
            是否有效
        """
        if self.valid_emotions is None:
            return True
        return emotion.lower() in self.valid_emotions
