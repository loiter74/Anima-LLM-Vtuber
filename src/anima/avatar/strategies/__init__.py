"""
时间轴策略模块

该模块定义了情绪时间轴计算策略的接口。
所有策略必须实现 ITimelineStrategy 接口。
"""

from .base import ITimelineStrategy, TimelineSegment, TimelineConfig
from .position_based import PositionBasedStrategy
from .duration_based import DurationBasedStrategy
from .intensity_based import IntensityBasedStrategy

__all__ = [
    "ITimelineStrategy",
    "TimelineSegment",
    "TimelineConfig",
    "PositionBasedStrategy",
    "DurationBasedStrategy",
    "IntensityBasedStrategy",
]
