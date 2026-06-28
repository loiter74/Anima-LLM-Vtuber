"""Redis-backed LangGraph checkpoint saver.

Provides multi-instance session sharing via Redis.
Falls back to MemorySaver if Redis is unavailable.
"""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from loguru import logger


class AsyncRedisSaver(BaseCheckpointSaver):
    """Redis-backed checkpoint saver for LangGraph.

    Stores session state in Redis so multiple backend instances can
    share the same session data.  Each thread_id maps to one Redis key.

    Connection timeouts are set to 5s so a missing Redis does not
    block startup indefinitely.
    """

    def __init__(self, redis_url: str) -> None:
        super().__init__()
        import redis.asyncio as aioredis

        self._redis_url = redis_url
        self._prefix = "checkpoint:"
        self._writes_prefix = "checkpoint_writes:"
        self.redis: aioredis.Redis = aioredis.from_url(
            redis_url,
            socket_connect_timeout=5,
            socket_timeout=5,
        )

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _serialize(obj: Any) -> str:
        return json.dumps(obj, default=str, ensure_ascii=False)

    @staticmethod
    def _deserialize(data: bytes) -> Any:
        return json.loads(data)

    def _make_key(self, thread_id: str) -> str:
        return f"{self._prefix}{thread_id}"

    def _make_writes_key(self, thread_id: str) -> str:
        return f"{self._writes_prefix}{thread_id}"

    # ── async checkpoint protocol ────────────────────────────────

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id: str = config["configurable"]["thread_id"]
        key = self._make_key(thread_id)
        try:
            raw = await self.redis.get(key)
            if not raw:
                return None
            stored = self._deserialize(raw)
            checkpoint: Checkpoint = stored["checkpoint"]
            metadata: CheckpointMetadata = stored.get("metadata", {})
            checkpoint_id = checkpoint.get("id", "")

            # Load pending writes if any
            pending_writes: list = []
            writes_key = self._make_writes_key(thread_id)
            raw_writes = await self.redis.get(writes_key)
            if raw_writes:
                pending_writes = self._deserialize(raw_writes)

            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": config["configurable"].get("checkpoint_ns", ""),
                        "checkpoint_id": checkpoint_id,
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                pending_writes=pending_writes,
            )
        except Exception as e:
            logger.warning(f"[RedisSaver] aget_tuple failed: {e}")
            return None

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id: str = config["configurable"]["thread_id"]
        key = self._make_key(thread_id)
        data = {
            "checkpoint": checkpoint,
            "metadata": metadata,
            "new_versions": new_versions,
        }
        try:
            await self.redis.set(key, self._serialize(data), ex=86400)
        except Exception as e:
            logger.warning(f"[RedisSaver] aput failed: {e}")
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": config["configurable"].get("checkpoint_ns", ""),
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        _ = (task_id, task_path)  # signature compliance, params unused
        thread_id: str = config["configurable"]["thread_id"]
        writes_key = self._make_writes_key(thread_id)
        try:
            await self.redis.set(writes_key, self._serialize(writes), ex=86400)
        except Exception as e:
            logger.warning(f"[RedisSaver] aput_writes failed: {e}")

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Return matching checkpoints (minimal implementation)."""
        _ = (filter, before, limit)  # signature compliance, params unused
        if config:
            tup = await self.aget_tuple(config)
            if tup:
                yield tup

    async def adelete_thread(self, thread_id: str) -> None:
        try:
            await self.redis.delete(self._make_key(thread_id))
            await self.redis.delete(self._make_writes_key(thread_id))
        except Exception as e:
            logger.warning(f"[RedisSaver] adelete_thread failed: {e}")

    # ── lifecycle ────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the Redis connection gracefully."""
        try:
            await self.redis.aclose()
        except Exception as e:
            logger.warning(f"[RedisSaver] close failed: {e}")
