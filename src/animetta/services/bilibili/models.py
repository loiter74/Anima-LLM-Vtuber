from __future__ import annotations

"""Unified data models for bilibili danmaku, meme collection, and interaction learning."""

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DanmakuMessage:
    """Single danmaku message (text, gift, or super chat) from a Bilibili live room.

    Merged from DanmakuMessage (live) + DanmakuSample (interaction).
    is_gift / is_super_chat default to False for plain text danmaku.
    meta holds event-specific data (gift_name, price, etc.).
    """
    text: str
    user_name: str = ""
    user_id: int = 0
    timestamp: float = field(default_factory=time.time)
    is_gift: bool = False
    is_super_chat: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DanmakuReply:
    """AI reply to a danmaku message."""
    danmaku_text: str
    reply_text: str
    user_name: str
    character_name: str = "AI"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DanmakuPhrase:
    """A high-frequency phrase extracted from recent danmaku."""
    text: str
    frequency: int
    first_seen: float  # Unix timestamp
    last_seen: float   # Unix timestamp
    source_room_id: int = 0


@dataclass
class CollectedVideo:
    """Raw video data collected from B站."""
    bvid: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    view_count: int = 0
    danmaku_count: int = 0
    reply_count: int = 0

    def to_dict(self) -> dict:
        return {
            "bvid": self.bvid,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "view_count": self.view_count,
            "danmaku_count": self.danmaku_count,
            "reply_count": self.reply_count,
        }


@dataclass
class CollectedComment:
    """Raw comment data collected from B站."""
    content: str
    likes: int = 0
    replies: int = 0
    publish_time: str = ""

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "likes": self.likes,
            "replies": self.replies,
            "publish_time": self.publish_time,
        }


@dataclass
class CollectedDanmaku:
    """Raw danmaku (弹幕) data collected from B站 videos."""
    content: str
    source_video: str = ""  # BV ID
    source_type: str = "video"  # video, live, comment
    likes: int = 0
    publish_time: str = ""
    mode: int = 1  # 1=scroll, 4=bottom, 5=top, etc.
    color: int = 16777215  # RGB color
    is_meme: bool = False
    meme_type: str = ""  # 热梗, 搞笑, 情感, etc.
    quality_score: float = 0.0  # 0.0-1.0

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "source_video": self.source_video,
            "source_type": self.source_type,
            "likes": self.likes,
            "publish_time": self.publish_time,
            "mode": self.mode,
            "color": self.color,
            "is_meme": self.is_meme,
            "meme_type": self.meme_type,
            "quality_score": self.quality_score,
        }


@dataclass
class MemeCandidate:
    """Meme candidate identified from B站 content before cognitive analysis.

    Renamed from MemeCandidateRaw — "Raw" is redundant since all candidates
    start as raw before cognitive analysis.
    """
    text: str
    context_hint: str = ""
    frequency: int = 1
    source_videos: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    format_id: str = ""
    format_slots: dict[str, str] = field(default_factory=dict)
    format_confidence: float | None = None
    rendered_text: str = ""
    mode: str = ""

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "context_hint": self.context_hint,
            "frequency": self.frequency,
            "source_videos": self.source_videos,
            "tags": self.tags,
            "format_id": self.format_id,
            "format_slots": self.format_slots,
            "format_confidence": self.format_confidence,
            "rendered_text": self.rendered_text,
            "mode": self.mode,
        }


@dataclass
class InteractionPattern:
    """Analyzed interaction pattern from livestream danmaku."""
    name: str
    description: str
    applicable_scenarios: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "applicable_scenarios": self.applicable_scenarios,
            "confidence": self.confidence,
        }


@dataclass
class LivestreamStrategy:
    """Actionable livestream optimization strategy."""
    trigger_condition: str
    suggested_behavior: str
    expected_effect: str
    priority: str = "medium"  # high / medium / low

    def to_dict(self) -> dict:
        return {
            "trigger_condition": self.trigger_condition,
            "suggested_behavior": self.suggested_behavior,
            "expected_effect": self.expected_effect,
            "priority": self.priority,
        }
