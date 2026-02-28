"""
情绪分析器模块

该模块定义了情绪分析器的接口和数据结构。
所有情绪分析器必须实现 IEmotionAnalyzer 接口。
"""

from .base import IEmotionAnalyzer, EmotionData
from .llm_tag_analyzer import LLMTagAnalyzer
from .keyword_analyzer import KeywordAnalyzer

__all__ = [
    "IEmotionAnalyzer",
    "EmotionData",
    "LLMTagAnalyzer",
    "KeywordAnalyzer",
]
