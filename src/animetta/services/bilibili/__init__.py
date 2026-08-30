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
from .gateway import DanmakuGateway, DanmakuServiceGateway, create_danmaku_gateway
from .interaction_learner import InteractionLearner
from .livestream_session import LivestreamSession
from .livestream_state import LivestreamSnapshot, LivestreamState
from .meme_collector import CollectedComment, CollectedVideo, MemeCandidate, MemeCollector
from .models import (
    CollectedDanmaku,
    DanmakuMessage,
    DanmakuReply,
    InteractionPattern,
    LivestreamEvent,
    LivestreamEventMetrics,
    LivestreamEventType,
    LivestreamStrategy,
)
from .proactive_topics import (
    DeadpanLogicSource,
    ProactiveTopicMetrics,
    ProactiveTopicRuntime,
    SceneTopicSource,
    TopicContext,
    TopicSeed,
    TopicSource,
)
from .replay_gateway import (
    HIGH_HEAT_BURSTS,
    BurstWindow,
    ReplayDanmakuGateway,
    ReplayMetrics,
    ReplayTimeline,
)
from .reply_admission import AdmissionDecision, ReplyAdmissionController, ReplyPriority
from .reply_queue import (
    BoundedReplyQueue,
    DanmakuReplyRuntime,
    QueuePutResult,
    ReplyCandidate,
    ReplyMetrics,
    ReplySubmissionResult,
    ReplyWorker,
)
from .response_policy import (
    LIVESTREAM_REPLY_MAX_CHARS,
    MINECRAFT_NARRATION_REPLY_MAX_CHARS,
    MINECRAFT_NARRATION_SOURCE,
    PROACTIVE_TOPIC_REPLY_MAX_CHARS,
    PROACTIVE_TOPIC_SOURCE,
    constrain_livestream_response,
    constrain_minecraft_narration_response,
    constrain_proactive_topic_response,
    is_minecraft_narration_turn,
    is_proactive_topic_turn,
    normalize_proactive_topic_text,
)

__all__ = [
    "DanmakuService",
    "DanmakuGateway",
    "DanmakuServiceGateway",
    "create_danmaku_gateway",
    "LivestreamSession",
    "LivestreamSnapshot",
    "LivestreamState",
    "AdmissionDecision",
    "ReplyAdmissionController",
    "ReplyPriority",
    "BoundedReplyQueue",
    "DanmakuReplyRuntime",
    "QueuePutResult",
    "ReplyCandidate",
    "ReplyMetrics",
    "ReplySubmissionResult",
    "ReplyWorker",
    "LIVESTREAM_REPLY_MAX_CHARS",
    "constrain_livestream_response",
    "MINECRAFT_NARRATION_REPLY_MAX_CHARS",
    "MINECRAFT_NARRATION_SOURCE",
    "constrain_minecraft_narration_response",
    "PROACTIVE_TOPIC_REPLY_MAX_CHARS",
    "PROACTIVE_TOPIC_SOURCE",
    "constrain_proactive_topic_response",
    "is_minecraft_narration_turn",
    "is_proactive_topic_turn",
    "normalize_proactive_topic_text",
    "TopicSeed",
    "TopicContext",
    "TopicSource",
    "SceneTopicSource",
    "DeadpanLogicSource",
    "ProactiveTopicMetrics",
    "ProactiveTopicRuntime",
    "DanmakuMessage",
    "DanmakuReply",
    "LivestreamEvent",
    "LivestreamEventMetrics",
    "LivestreamEventType",
    "BurstWindow",
    "HIGH_HEAT_BURSTS",
    "ReplayDanmakuGateway",
    "ReplayMetrics",
    "ReplayTimeline",
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
