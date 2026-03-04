"""
Live2D 模块
提供基于情感内容的 Live2D 表情控制

新架构使用插件式情绪分析器和策略模式。
"""

# 新的插件式架构
from .analyzers.base import IEmotionAnalyzer, EmotionData
from .analyzers.standalone_llm_analyzer import (
    StandaloneLLMTagAnalyzer,
    EmotionTag,
    EmotionExtractionResult
)
from .strategies.base import ITimelineStrategy, TimelineSegment
from .factory import (
    EmotionAnalyzerFactory,
    TimelineStrategyFactory,
    create_emotion_analyzer,
    create_timeline_strategy,
)

# 保留的工具类
from .audio_analyzer import AudioAnalyzer
from .prompt_builder import EmotionPromptBuilder

__all__ = [
    # 新架构 - 分析器
    "IEmotionAnalyzer",
    "EmotionData",
    "StandaloneLLMTagAnalyzer",
    "EmotionTag",
    "EmotionExtractionResult",
    # 新架构 - 策略
    "ITimelineStrategy",
    "TimelineSegment",
    # 新架构 - 工厂
    "EmotionAnalyzerFactory",
    "TimelineStrategyFactory",
    "create_emotion_analyzer",
    "create_timeline_strategy",
    # 工具类
    "AudioAnalyzer",
    "EmotionPromptBuilder",
]
