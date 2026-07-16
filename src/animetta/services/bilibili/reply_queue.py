"""Bounded priority queue and serialized worker for AI danmaku replies."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loguru import logger

from animetta.config import ReplyPolicyConfig

from .models import DanmakuMessage
from .reply_admission import ReplyAdmissionController, ReplyPriority


@dataclass(frozen=True, slots=True)
class ReplyCandidate:
    """An admitted message bound to one livestream generation."""

    message: DanmakuMessage
    priority: ReplyPriority
    generation_id: int
    admitted_at: float
    room_id: int = 0


@dataclass(frozen=True, slots=True)
class QueuePutResult:
    """Outcome of inserting a candidate into a bounded queue."""

    accepted: bool
    reason: str | None = None
    evicted: ReplyCandidate | None = None


@dataclass(slots=True)
class ReplyMetrics:
    """In-memory counters for raw delivery and AI reply processing."""

    received: int = 0
    displayed: int = 0
    admitted: int = 0
    dropped: Counter[str] = field(default_factory=Counter)
    reply_success: int = 0
    reply_failure: int = 0
    queue_depth: int = 0
    reply_latency_seconds: list[float] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _QueueEntry:
    sequence: int
    candidate: ReplyCandidate


class BoundedReplyQueue:
    """Priority queue with deterministic lower-priority eviction."""

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        self._entries: list[_QueueEntry] = []
        self._sequence = 0
        self._closed = False
        self._condition = asyncio.Condition()

    @property
    def qsize(self) -> int:
        """Return the current number of queued candidates."""
        return len(self._entries)

    async def put(self, candidate: ReplyCandidate) -> QueuePutResult:
        """Insert a candidate, evicting the oldest lower-priority item if needed."""
        async with self._condition:
            if self._closed:
                return QueuePutResult(accepted=False, reason="queue_closed")

            evicted: ReplyCandidate | None = None
            reason: str | None = None
            if len(self._entries) >= self._max_size:
                lower_priority = [
                    entry
                    for entry in self._entries
                    if entry.candidate.priority > candidate.priority
                ]
                if not lower_priority:
                    return QueuePutResult(accepted=False, reason="queue_full")
                victim = min(lower_priority, key=lambda entry: entry.sequence)
                self._entries.remove(victim)
                evicted = victim.candidate
                reason = "evicted_lower_priority"

            entry = _QueueEntry(sequence=self._sequence, candidate=candidate)
            self._sequence += 1
            self._entries.append(entry)
            self._condition.notify(1)
            return QueuePutResult(accepted=True, reason=reason, evicted=evicted)

    async def get(self) -> ReplyCandidate | None:
        """Wait for and remove the highest-priority, oldest candidate."""
        async with self._condition:
            while not self._entries and not self._closed:
                await self._condition.wait()
            if not self._entries:
                return None
            entry = min(
                self._entries,
                key=lambda item: (item.candidate.priority, item.sequence),
            )
            self._entries.remove(entry)
            return entry.candidate

    async def discard_except_generation(self, generation_id: int) -> int:
        """Discard queued candidates not owned by ``generation_id``."""
        async with self._condition:
            retained = [
                entry for entry in self._entries if entry.candidate.generation_id == generation_id
            ]
            removed = len(self._entries) - len(retained)
            self._entries = retained
            return removed

    async def close(self) -> None:
        """Wake waiting consumers and reject future candidates."""
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


ReplyProcessor = Callable[[ReplyCandidate], Awaitable[None]]


class ReplyWorker:
    """Process admitted replies serially while isolating item failures."""

    def __init__(
        self,
        *,
        queue: BoundedReplyQueue,
        processor: ReplyProcessor,
        metrics: ReplyMetrics,
        generation_id: int,
        max_message_age_seconds: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._queue = queue
        self._processor = processor
        self._metrics = metrics
        self._generation_id = generation_id
        self._max_message_age_seconds = max_message_age_seconds
        self._clock = clock

    async def run(self) -> None:
        """Run until the queue is closed and drained."""
        while True:
            candidate = await self._queue.get()
            self._metrics.queue_depth = self._queue.qsize
            if candidate is None:
                return
            if candidate.generation_id != self._generation_id:
                self._metrics.dropped["stale_generation"] += 1
                continue
            if self._clock() - candidate.message.timestamp > self._max_message_age_seconds:
                self._metrics.dropped["expired"] += 1
                continue

            started_at = self._clock()
            try:
                await self._processor(candidate)
            except Exception as exc:
                self._metrics.reply_failure += 1
                self._metrics.dropped["reply_failed"] += 1
                logger.error(
                    "Danmaku reply processing failed: error_type={}",
                    type(exc).__name__,
                )
                continue

            self._metrics.reply_success += 1
            self._metrics.reply_latency_seconds.append(
                max(0.0, self._clock() - started_at),
            )

    async def stop(self) -> None:
        """Stop after already queued items are drained."""
        await self._queue.close()


class DanmakuReplyRuntime:
    """Own admission, queue, worker, and metrics for one session generation."""

    def __init__(
        self,
        policy: ReplyPolicyConfig,
        processor: ReplyProcessor,
    ) -> None:
        self._policy = policy
        self._processor = processor
        self._admission = ReplyAdmissionController(policy)
        self._queue: BoundedReplyQueue | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._generation_id = 0
        self.metrics = ReplyMetrics()

    @property
    def worker_running(self) -> bool:
        """Whether the generation's serialized reply worker is active."""
        return self._worker_task is not None and not self._worker_task.done()

    def configure(self, policy: ReplyPolicyConfig) -> None:
        """Replace policy before a session starts processing messages."""
        if self.worker_running:
            raise RuntimeError("cannot configure an active reply runtime")
        self._policy = policy
        self._admission = ReplyAdmissionController(policy)

    async def switch_generation(self, generation_id: int) -> None:
        """Atomically cancel all work owned by an older generation."""
        if generation_id == self._generation_id:
            return

        queue = self._queue
        task = self._worker_task
        if queue is not None:
            self.metrics.dropped["stale_generation"] += queue.qsize
            await queue.close()
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._queue = None
        self._worker_task = None
        self._generation_id = generation_id
        self.metrics.queue_depth = 0

    async def submit(
        self,
        message: DanmakuMessage,
        *,
        room_id: int,
        generation_id: int,
    ) -> None:
        """Admit and enqueue one message for the current generation."""
        if generation_id != self._generation_id:
            self.metrics.dropped["stale_generation"] += 1
            return

        decision = self._admission.decide(message)
        if not decision.admitted or decision.priority is None:
            self.metrics.dropped[decision.reason or "rejected"] += 1
            return

        self._ensure_worker()
        assert self._queue is not None
        result = await self._queue.put(
            ReplyCandidate(
                message=message,
                priority=decision.priority,
                generation_id=generation_id,
                admitted_at=time.time(),
                room_id=room_id,
            ),
        )
        if not result.accepted:
            self.metrics.dropped[result.reason or "queue_rejected"] += 1
            return
        self.metrics.admitted += 1
        if result.evicted is not None:
            self.metrics.dropped["queue_evicted"] += 1
        self.metrics.queue_depth = self._queue.qsize

    async def close(self) -> None:
        """Cancel all reply work and release owned queue resources."""
        queue = self._queue
        task = self._worker_task
        if queue is not None:
            self.metrics.dropped["stale_generation"] += queue.qsize
            await queue.close()
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._queue = None
        self._worker_task = None
        self.metrics.queue_depth = 0

    def _ensure_worker(self) -> None:
        if self.worker_running:
            return
        self._queue = BoundedReplyQueue(self._policy.max_queue_size)
        worker = ReplyWorker(
            queue=self._queue,
            processor=self._processor,
            metrics=self.metrics,
            generation_id=self._generation_id,
            max_message_age_seconds=self._policy.max_message_age_seconds,
        )
        self._worker_task = asyncio.create_task(
            worker.run(),
            name=f"bilibili-reply-{self._generation_id}",
        )
