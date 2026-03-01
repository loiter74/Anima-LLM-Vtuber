"""
情绪分析器模块

该模块定义了情绪分析器的接口和数据结构。
所有情绪分析器必须实现 IEmotionAnalyzer 接口。
"""

from .base import IEmotionAnalyzer, EmotionData
from .keyword_analyzer import KeywordAnalyzer
from .standalone_llm_analyzer import (
    StandaloneLLMTagAnalyzer,
    EmotionTag,
    EmotionExtractionResult
)

__all__ = [
    "IEmotionAnalyzer",
    "EmotionData",
    "KeywordAnalyzer",
    "StandaloneLLMTagAnalyzer",
    "EmotionTag",
    "EmotionExtractionResult",
]
