"""Bilibili danmaku configuration model."""

from pydantic import Field

from ..core.base import BaseConfig


class ReplyPolicyConfig(BaseConfig):
    """Deterministic admission and backpressure settings for AI replies."""

    enabled: bool = True
    max_replies_per_minute: int = Field(default=6, ge=1, le=60)
    max_queue_size: int = Field(default=20, ge=1, le=1000)
    max_message_age_seconds: int = Field(default=15, ge=1, le=300)
    per_user_cooldown_seconds: int = Field(default=30, ge=0, le=3600)
    duplicate_window_seconds: int = Field(default=60, ge=0, le=3600)
    ordinary_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    reply_to_gifts: bool = True
    reply_to_super_chat: bool = True


class BilibiliConfig(BaseConfig):
    """Bilibili live danmaku integration config.

    Controls whether the bilibili live danmaku service is enabled
    and which room to connect to. The sessdata cookie enables
    authenticated access for premium features.
    """

    enabled: bool = Field(default=False, description="Enable bilibili live danmaku integration")
    room_id: int = Field(default=0, ge=0, description="Bilibili live room ID to connect to")
    sessdata: str = Field(
        default="", description="Bilibili SESSDATA cookie for authenticated access"
    )
    reply_policy: ReplyPolicyConfig = Field(default_factory=ReplyPolicyConfig)

    def to_public_dict(self) -> dict[str, object]:
        """Return client-safe settings without authentication material."""
        return self.model_dump(exclude={"sessdata"})
