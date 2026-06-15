"""Bilibili danmaku service package — live chat, meme collection, interaction learning.

Provides:
    DanmakuService      — WebSocket-based live danmaku listener
    MemeCollector       — Trending video + comment collection + meme identification
    InteractionLearner  — Danmaku interaction pattern analysis + strategy generation
    DanmakuBuffer       — Ring buffer for real-time danmaku phrase tracking
    CollectedDanmaku    — Danmaku data model for training data
    fetch_video_danmaku — API function to fetch danmaku from videos
"""

from .api import fetch_video_danmaku
from .danmaku_buffer import DanmakuBuffer, DanmakuPhrase
from .danmaku_service import DanmakuService
from .interaction_learner import InteractionLearner
from .meme_collector import CollectedComment, CollectedVideo, MemeCandidate, MemeCollector
from .models import (
    CollectedDanmaku,
    DanmakuMessage,
    DanmakuReply,
    InteractionPattern,
    LivestreamStrategy,
)

__all__ = [
    "DanmakuService",
    "DanmakuMessage",
    "DanmakuReply",
    "DanmakuBuffer",
    "DanmakuPhrase",
    "MemeCollector",
    "CollectedVideo",
    "CollectedComment",
    "CollectedDanmaku",
    "MemeCandidate",
    "InteractionLearner",
    "InteractionPattern",
    "LivestreamStrategy",
    "fetch_video_danmaku",
]
