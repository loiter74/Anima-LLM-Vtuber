"""Application-scoped owner for Animetta's stateful memory runtime."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from animetta.memory.v2.atom import MemoryScope, MemoryVisibility
from animetta.memory.v2.context import MemoryContext
from animetta.memory.v2.emotion_field import VADVector
from animetta.memory.v2.system import LivingMemorySystem


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """Validated output candidate submitted by the live graph."""

    user_input: str
    agent_response: str
    context: MemoryContext
    emotion_vad: VADVector | None = None
    turn_id: str | None = None
    is_probe: bool = False
    is_fallback: bool = False
    requested_scope: MemoryScope | None = None
    retention_policy: str = "standard"


class SharedMemoryRuntime:
    """Own one memory system and its background maintenance workers.

    Session contexts borrow ``system``. Only this runtime initializes and shuts
    it down, so transport disconnects cannot destroy application memory.
    """

    def __init__(
        self,
        db_path: str | Path = "memory_db/living_memory.sqlite",
        *,
        system_factory: Callable[[], Any] | None = None,
        worker_interval: float = 0.5,
        ingestion_queue_size: int = 256,
        dedup_window: int = 2048,
    ) -> None:
        self.db_path = str(db_path)
        self._system_factory = system_factory or (
            lambda: LivingMemorySystem(db_path=self.db_path)
        )
        self.worker_interval = worker_interval
        self.system: Any | None = None
        self._initialize_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._index_task: asyncio.Task[None] | None = None
        self._ingestion_task: asyncio.Task[None] | None = None
        self._ingestion_queue: asyncio.Queue[ConversationTurn] = asyncio.Queue(
            maxsize=max(1, ingestion_queue_size)
        )
        self._dedup: OrderedDict[str, None] = OrderedDict()
        self._dedup_window = max(1, dedup_window)
        self._revision_subscribers: list[Callable[[dict[str, object]], Any]] = []
        self._ingestion_rejected = 0
        self._ingestion_dropped = 0
        self._ingestion_failed = 0
        self._stopping = asyncio.Event()
        self._initialized = False
        self._closed = False

    @property
    def is_ready(self) -> bool:
        return self._initialized and not self._closed and self.system is not None

    async def initialize(self) -> None:
        """Initialize the system and workers exactly once."""

        if self.is_ready:
            return
        async with self._initialize_lock:
            if self.is_ready:
                return
            if self._closed:
                raise RuntimeError("SharedMemoryRuntime cannot restart after shutdown")
            system = self._system_factory()
            await system.initialize()
            await system.start_metabolism()
            self.system = system
            self._stopping.clear()
            self._index_task = asyncio.create_task(
                self._index_worker(), name="animetta-memory-index-worker"
            )
            self._ingestion_task = asyncio.create_task(
                self._ingestion_worker(), name="animetta-memory-ingestion-worker"
            )
            self._initialized = True
            logger.info("[SharedMemoryRuntime] Ready: {}", self.db_path)

    async def _index_worker(self) -> None:
        while not self._stopping.is_set():
            system = self.system
            if system is not None:
                try:
                    await system.store.process_index_outbox()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("[SharedMemoryRuntime] Index worker degraded: {}", exc)
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self.worker_interval
                )
            except TimeoutError:
                continue

    def subscribe_revision(
        self,
        callback: Callable[[dict[str, object]], Any],
    ) -> Callable[[], None]:
        """Subscribe to committed memory revisions and return an unsubscribe hook."""
        self._revision_subscribers.append(callback)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._revision_subscribers.remove(callback)

        return unsubscribe

    def submit_turn(self, turn: ConversationTurn) -> bool:
        """Submit without awaiting storage; reject invalid/duplicate/overflow turns."""
        if not self.is_ready or turn.is_probe or turn.is_fallback:
            self._ingestion_rejected += 1
            return False
        if not turn.user_input.strip() or not turn.agent_response.strip():
            self._ingestion_rejected += 1
            return False

        fingerprint = self._fingerprint(turn)
        if fingerprint in self._dedup:
            self._ingestion_rejected += 1
            return False
        try:
            self._ingestion_queue.put_nowait(turn)
        except asyncio.QueueFull:
            self._ingestion_dropped += 1
            return False
        self._dedup[fingerprint] = None
        while len(self._dedup) > self._dedup_window:
            self._dedup.popitem(last=False)
        return True

    @staticmethod
    def _fingerprint(turn: ConversationTurn) -> str:
        normalized = "|".join((
            turn.context.actor_id or "anonymous",
            turn.context.conversation_id or "",
            " ".join(turn.user_input.casefold().split()),
            " ".join(turn.agent_response.casefold().split()),
        ))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def _ingestion_worker(self) -> None:
        while True:
            try:
                turn = await self._ingestion_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                await self._ingest(turn)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ingestion_failed += 1
                logger.warning("[SharedMemoryRuntime] Ingestion failed: {}", exc)
            finally:
                self._ingestion_queue.task_done()

    async def _ingest(self, turn: ConversationTurn) -> None:
        system = self.system
        if system is None:
            return
        scope, visibility = self._safe_scope(turn)
        atom = await system.encode(
            user_input=turn.user_input,
            agent_response=turn.agent_response,
            emotion_vad=turn.emotion_vad,
            context=turn.context,
            scope=scope,
            visibility=visibility,
            retention_policy=turn.retention_policy,
        )
        revision = await system.store.get_revision()
        payload: dict[str, object] = {
            "revision": revision,
            "reason": "ingested",
            "atom_id": atom.id,
        }
        for callback in tuple(self._revision_subscribers):
            try:
                result = callback(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.warning("[SharedMemoryRuntime] Revision subscriber failed: {}", exc)

    @staticmethod
    def _safe_scope(
        turn: ConversationTurn,
    ) -> tuple[MemoryScope, MemoryVisibility]:
        requested = turn.requested_scope
        # Canonical character memory is authored by controlled compilation,
        # never copied directly from a viewer/model conversation.
        if requested is MemoryScope.CHARACTER:
            requested = None
        if requested is MemoryScope.VIEWER and not turn.context.actor_id:
            requested = None
        if requested is MemoryScope.STREAM and not turn.context.stream_id:
            requested = None
        scope = requested or (
            MemoryScope.VIEWER
            if turn.context.actor_id
            else MemoryScope.STREAM
            if turn.context.stream_id
            else MemoryScope.COMMUNITY
        )
        visibility = (
            MemoryVisibility.PRIVATE
            if scope is MemoryScope.VIEWER
            else MemoryVisibility.INTERNAL
        )
        return scope, visibility

    async def drain(self, timeout: float = 5.0) -> None:
        """Wait for accepted ingestion work to commit."""
        await asyncio.wait_for(self._ingestion_queue.join(), timeout=timeout)

    async def shutdown(self) -> None:
        """Stop workers and close the owned memory system exactly once."""

        if self._closed:
            return
        async with self._shutdown_lock:
            if self._closed:
                return
            self._stopping.set()
            if self._ingestion_task is not None:
                with contextlib.suppress(TimeoutError):
                    await self.drain()
                self._ingestion_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._ingestion_task
                self._ingestion_task = None
            task = self._index_task
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                self._index_task = None
            if self.system is not None:
                await self.system.shutdown()
                self.system = None
            self._closed = True
            self._initialized = False
            logger.info("[SharedMemoryRuntime] Closed")

    async def health(self) -> dict[str, object]:
        """Return readiness, revision, and derived-index state."""

        if not self.is_ready or self.system is None:
            return {
                "ready": False,
                "degraded": True,
                "revision": 0,
                "index_backlog": 0,
                "last_error": "memory runtime not initialized",
            }
        store = self.system.store
        index_health = store.get_index_health()
        return {
            "ready": True,
            "degraded": bool(index_health["degraded"]),
            "revision": await store.get_revision(),
            "index_backlog": await store.get_index_backlog(),
            "last_error": index_health["last_error"],
            "ingestion_queue": self._ingestion_queue.qsize(),
            "ingestion_rejected": self._ingestion_rejected,
            "ingestion_dropped": self._ingestion_dropped,
            "ingestion_failed": self._ingestion_failed,
        }
