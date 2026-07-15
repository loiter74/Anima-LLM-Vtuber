"""
Emotion Analyzer Module

Contains various Live2D emotion analyzers
"""

from .audio import AudioAnalyzer
from .base import EmotionData, IEmotionAnalyzer
from .keyword import KeywordAnalyzer
from .llm_tag import EmotionExtractionResult, EmotionTag, StandaloneLLMTagAnalyzer

__all__ = [
    "IEmotionAnalyzer",
    "EmotionData",
    "KeywordAnalyzer",
    "StandaloneLLMTagAnalyzer",
    "EmotionTag",
    "EmotionExtractionResult",
    "AudioAnalyzer",
]
