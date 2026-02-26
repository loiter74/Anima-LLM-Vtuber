"""
Live2D 模块
提供基于情感内容的 Live2D 表情控制
"""

from .emotion_extractor import EmotionExtractor, EmotionTag, EmotionExtractionResult
from .emotion_timeline import EmotionTimelineCalculator, EmotionTimeline, EmotionSegment
from .audio_analyzer import AudioAnalyzer
from .prompt_builder import EmotionPromptBuilder

__all__ = [
    "EmotionExtractor",
    "EmotionTag",
    "EmotionExtractionResult",
    "EmotionTimelineCalculator",
    "EmotionTimeline",
    "EmotionSegment",
    "AudioAnalyzer",
    "EmotionPromptBuilder",
]
