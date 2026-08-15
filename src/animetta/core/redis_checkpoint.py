"""Lifecycle owner for the official LangGraph Redis checkpointer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass(frozen=True, slots=True)
class CheckpointHealth:
    available: bool
    degraded: bool
    reason: str | None

    def public_dict(self) -> dict[str, object | None]:
        return {
            "state": "ready" if self.available else "degraded",
            "ready": self.available,
            "degraded": self.degraded,
            "reason": self.reason,
        }


class RedisCheckpointRuntime:
    """Own one official ``AsyncRedisSaver`` for the application lifespan."""

    def __init__(self, redis_url: str | None = None, *, ttl_minutes: int = 1440) -> None:
        self.redis_url = redis_url or os.getenv("ANIMETTA_REDIS_URL")
        self.ttl_minutes = ttl_minutes
        self.saver: Any | None = None
        self._context: Any | None = None
        self.health = CheckpointHealth(False, True, "redis_url_missing")

    async def start(self) -> CheckpointHealth:
        if self.saver is not None:
            return self.health
        if not self.redis_url:
            return self.health
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver

            self._context = AsyncRedisSaver.from_conn_string(
                self.redis_url,
                ttl={
                    "default_ttl": self.ttl_minutes,
                    "refresh_on_read": True,
                },
            )
            self.saver = await self._context.__aenter__()
            self.health = CheckpointHealth(True, False, None)
            logger.info("[Checkpoint] Official Redis checkpointer is ready")
        except Exception as exc:
            self.saver = None
            self._context = None
            self.health = CheckpointHealth(False, True, "checkpoint_unavailable")
            logger.warning(
                "[Checkpoint] Redis unavailable: error_type={}",
                type(exc).__name__,
            )
        return self.health

    async def check_health(self) -> CheckpointHealth:
        """Refresh content-free readiness against the saver-owned Redis client."""
        if self.saver is None:
            return await self.start() if self.redis_url else self.health
        try:
            redis_client = getattr(self.saver, "_redis")
            await redis_client.ping()
            self.health = CheckpointHealth(True, False, None)
        except Exception as exc:
            self.health = CheckpointHealth(False, True, "checkpoint_unavailable")
            logger.warning(
                "[Checkpoint] Redis health check failed: error_type={}",
                type(exc).__name__,
            )
        return self.health

    async def delete_thread(self, thread_id: str) -> None:
        if self.saver is None:
            return
        await self.saver.adelete_thread(thread_id)

    async def has_thread(self, thread_id: str) -> bool:
        if self.saver is None:
            raise RuntimeError("checkpoint saver is unavailable")
        checkpoint = await self.saver.aget_tuple({"configurable": {"thread_id": thread_id}})
        return checkpoint is not None

    async def close(self) -> None:
        context, self._context = self._context, None
        self.saver = None
        if context is not None:
            await context.__aexit__(None, None, None)
        self.health = CheckpointHealth(False, True, "closed")
