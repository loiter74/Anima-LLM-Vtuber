"""Strict versioned contracts for room-level scene analysis."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SceneContract(BaseModel):
    """Immutable JSON contract shared across scene-analysis boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1


class SceneEventType(StrEnum):
    DANMAKU = "danmaku"
    SUPER_CHAT = "super_chat"
    GIFT = "gift"
    HOST_REPLY = "host_reply"
    SYSTEM = "system"
    AUDIENCE_REACTION = "audience_reaction"


class SceneStage(StrEnum):
    WARMING = "warming"
    STEADY = "steady"
    TOPIC_RISING = "topic_rising"
    CLIMAX = "climax"
    COOLDOWN = "cooldown"


class ScenePace(StrEnum):
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"
    VERY_FAST = "very_fast"


class Atmosphere(StrEnum):
    NEUTRAL = "neutral"
    WARM = "warm"
    PLAYFUL = "playful"
    EXCITED = "excited"
    TENSE = "tense"


class EngagementLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Trend(StrEnum):
    FALLING = "falling"
    STABLE = "stable"
    RISING = "rising"


class MemeLifecycle(StrEnum):
    DISCOVERED = "discovered"
    RISING = "rising"
    PEAK = "peak"
    OVERUSED = "overused"
    COOLDOWN = "cooldown"


class NormalizedSceneEvent(SceneContract):
    event_id: str = Field(min_length=1, max_length=128)
    event_seq: int = Field(ge=1)
    session_id: str = Field(min_length=1, max_length=128)
    room_id: int = Field(gt=0)
    generation_id: int = Field(ge=0)
    occurred_at: float = Field(ge=0)
    event_type: SceneEventType
    actor_id: str | None = Field(default=None, max_length=128)
    actor_name: str | None = Field(default=None, max_length=80)
    text: str = Field(default="", max_length=500)
    amount: float | None = Field(default=None, ge=0)
    critical: bool = False


class SceneMetrics(SceneContract):
    event_count: int = Field(default=0, ge=0)
    danmaku_per_minute: float = Field(default=0, ge=0)
    unique_users: int = Field(default=0, ge=0)
    repeat_ratio: float = Field(default=0, ge=0, le=1)
    sentiment_delta: float = Field(default=0, ge=-1, le=1)
    critical_event_count: int = Field(default=0, ge=0)


class RuleHit(SceneContract):
    rule: str = Field(min_length=1, max_length=80)
    strength: float = Field(ge=0, le=1)
    subject: str | None = Field(default=None, max_length=80)


class SceneEvidence(SceneContract):
    session_id: str = Field(min_length=1, max_length=128)
    room_id: int = Field(gt=0)
    generation_id: int = Field(ge=0)
    from_event_seq: int = Field(ge=0)
    to_event_seq: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    metrics: SceneMetrics = Field(default_factory=SceneMetrics)
    rule_hits: list[RuleHit] = Field(default_factory=list, max_length=12)
    representative_events: list[NormalizedSceneEvent] = Field(default_factory=list, max_length=8)


class TopicState(SceneContract):
    label: str = Field(min_length=1, max_length=80)
    heat: float = Field(default=0.5, ge=0, le=1)
    trend: Trend = Trend.STABLE
    last_event_seq: int = Field(default=0, ge=0)


class MemeSceneState(SceneContract):
    meme_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=80)
    lifecycle: MemeLifecycle = MemeLifecycle.DISCOVERED
    mentions: int = Field(default=1, ge=1)
    last_event_seq: int = Field(default=0, ge=0)


class OpenLoop(SceneContract):
    loop_id: str = Field(min_length=1, max_length=128)
    kind: Literal["question", "super_chat", "gift", "promise", "topic"]
    summary: str = Field(min_length=1, max_length=200)
    created_event_seq: int = Field(ge=0)


class LiveSceneState(SceneContract):
    session_id: str = Field(min_length=1, max_length=128)
    room_id: int = Field(gt=0)
    generation_id: int = Field(ge=0)
    state_revision: int = Field(default=0, ge=0)
    last_event_seq: int = Field(default=0, ge=0)
    scene_stage: SceneStage = SceneStage.WARMING
    pace: ScenePace = ScenePace.NORMAL
    atmosphere: Atmosphere = Atmosphere.NEUTRAL
    engagement_level: EngagementLevel = EngagementLevel.LOW
    engagement_trend: Trend = Trend.STABLE
    scene_summary: str = Field(default="Livestream is starting.", max_length=300)
    topics: list[TopicState] = Field(default_factory=list, max_length=8)
    meme_states: list[MemeSceneState] = Field(default_factory=list, max_length=8)
    open_loops: list[OpenLoop] = Field(default_factory=list, max_length=8)
    recent_host_actions: list[str] = Field(default_factory=list, max_length=6)
    confidence: float = Field(default=0, ge=0, le=1)
    generated_at: float = Field(ge=0)
    expires_at: float = Field(ge=0)
    degraded: bool = False
    degradation_reasons: list[str] = Field(default_factory=list, max_length=6)

    @classmethod
    def initial(
        cls,
        *,
        session_id: str,
        room_id: int,
        generation_id: int,
        now: float,
        ttl_seconds: float = 60.0,
    ) -> LiveSceneState:
        return cls(
            session_id=session_id,
            room_id=room_id,
            generation_id=generation_id,
            generated_at=now,
            expires_at=now + ttl_seconds,
        )


class SceneStatePatch(SceneContract):
    base_revision: int = Field(ge=0)
    consumed_event_seq: int = Field(ge=0)
    scene_stage: SceneStage | None = None
    pace: ScenePace | None = None
    atmosphere: Atmosphere | None = None
    engagement_level: EngagementLevel | None = None
    engagement_trend: Trend | None = None
    scene_summary: str | None = Field(default=None, max_length=300)
    topic_upserts: list[TopicState] = Field(default_factory=list, max_length=8)
    topic_removals: list[str] = Field(default_factory=list, max_length=8)
    meme_upserts: list[MemeSceneState] = Field(default_factory=list, max_length=8)
    meme_removals: list[str] = Field(default_factory=list, max_length=8)
    open_loop_additions: list[OpenLoop] = Field(default_factory=list, max_length=8)
    resolved_open_loop_ids: list[str] = Field(default_factory=list, max_length=8)
    recent_host_action: str | None = Field(default=None, max_length=120)
    reason_codes: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=0, ge=0, le=1)
    generated_at: float = Field(ge=0)
    ttl_seconds: float = Field(default=60.0, gt=0, le=600)


class TechniqueSelection(SceneContract):
    technique_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=240)


class MemePolicy(SceneContract):
    action: Literal["none", "use", "avoid"] = "none"
    meme_id: str | None = Field(default=None, max_length=128)
    instruction: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_selection(self) -> MemePolicy:
        if self.action == "use" and not self.meme_id:
            raise ValueError("meme_id is required when action is use")
        return self


class ReplyScope(SceneContract):
    max_sentences: int = Field(default=2, ge=1, le=5)
    max_chars: int = Field(default=160, ge=20, le=500)
    allow_topic_switch: bool = False
    audience_target: Literal["whole_room", "current_viewer"] = "whole_room"


class SceneGuidance(SceneContract):
    scene_revision: int = Field(ge=0)
    scene_summary: str = Field(min_length=1, max_length=300)
    response_objective: str = Field(min_length=1, max_length=300)
    tone: list[str] = Field(default_factory=list, max_length=3)
    scope: ReplyScope = Field(default_factory=ReplyScope)
    must_address: list[str] = Field(default_factory=list, max_length=3)
    avoid: list[str] = Field(default_factory=list, max_length=5)
    technique: TechniqueSelection | None = None
    meme_policy: MemePolicy = Field(default_factory=MemePolicy)
    confidence: float = Field(ge=0, le=1)
    degraded: bool = False
    degradation_reasons: list[str] = Field(default_factory=list, max_length=6)
    expires_at: float = Field(ge=0)

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at
