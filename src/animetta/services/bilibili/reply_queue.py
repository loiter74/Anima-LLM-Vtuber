"""Bounded priority queue and serialized worker for AI danmaku replies."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import uuid4

from loguru import logger

from animetta.config import ReplyPolicyConfig

from .models import DanmakuMessage
from .reply_admission import ReplyAdmissionController, ReplyPriority
from .reply_media import (
    BroadcastMediaArbiter,
    BroadcastMediaTurn,
    OrderedReplyMediaCoordinator,
    ReplyMediaTurn,
)


@dataclass(frozen=True, slots=True)
class ReplyCandidate:
    """An admitted message bound to one livestream generation."""

    message: DanmakuMessage
    priority: ReplyPriority
    generation_id: int
    admitted_at: float
    room_id: int = 0
    reply_id: str = field(default_factory=lambda: str(uuid4()))
    sequence: int = 0
    media_turn: ReplyMediaTurn | None = None


@dataclass(frozen=True, slots=True)
class QueuePutResult:
    """Outcome of inserting a candidate into a bounded queue."""

    accepted: bool
    reason: str | None = None
    evicted: ReplyCandidate | None = None


@dataclass(frozen=True, slots=True)
class ReplySubmissionResult:
    """Auditable outcome of admission and bounded-queue submission."""

    admitted: bool
    reason: str | None = None
    priority: ReplyPriority | None = None
    evicted_lower_priority: bool = False
    evicted_message: DanmakuMessage | None = None


@dataclass(slots=True)
class ReplyMetrics:
    """In-memory counters for raw delivery and AI reply processing."""

    received: int = 0
    displayed: int = 0
    admitted: int = 0
    dropped: Counter[str] = field(default_factory=Counter)
    admitted_dropped: Counter[str] = field(default_factory=Counter)
    reply_success: int = 0
    reply_failure: int = 0
    reply_retries: int = 0
    queue_depth: int = 0
    max_queue_depth: int = 0
    queue_wait_seconds: list[float] = field(default_factory=list)
    reply_latency_seconds: list[float] = field(default_factory=list)

    @property
    def terminal_count(self) -> int:
        """Count every terminal outcome for an admitted candidate."""
        return self.reply_success + self.reply_failure + sum(self.admitted_dropped.values())


@dataclass(frozen=True, slots=True)
class _QueueEntry:
    sequence: int
    candidate: ReplyCandidate


class BoundedReplyQueue:
    """Priority queue with deterministic lower-priority eviction."""

    def __init__(self, max_size: int, *, prioritize: bool = True) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._max_size = max_size
        self._prioritize = prioritize
        self._entries: list[_QueueEntry] = []
        self._sequence = 0
        self._closed = False
        self._max_observed_size = 0
        self._condition = asyncio.Condition()

    @property
    def qsize(self) -> int:
        """Return the current number of queued candidates."""
        return len(self._entries)

    @property
    def max_observed_size(self) -> int:
        """Largest occupancy observed since this queue was created."""
        return self._max_observed_size

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
            self._max_observed_size = max(self._max_observed_size, len(self._entries))
            self._condition.notify(1)
            return QueuePutResult(accepted=True, reason=reason, evicted=evicted)

    async def put_wait(self, candidate: ReplyCandidate) -> QueuePutResult:
        """Wait for bounded capacity without silently evicting an admitted reply."""
        async with self._condition:
            while len(self._entries) >= self._max_size and not self._closed:
                await self._condition.wait()
            if self._closed:
                return QueuePutResult(accepted=False, reason="queue_closed")
            entry = _QueueEntry(sequence=self._sequence, candidate=candidate)
            self._sequence += 1
            self._entries.append(entry)
            self._max_observed_size = max(self._max_observed_size, len(self._entries))
            self._condition.notify_all()
            return QueuePutResult(accepted=True)

    async def get(self) -> ReplyCandidate | None:
        """Wait for and remove the highest-priority, oldest candidate."""
        async with self._condition:
            while not self._entries and not self._closed:
                await self._condition.wait()
            if not self._entries:
                return None
            entry = min(
                self._entries,
                key=(
                    (lambda item: (item.candidate.priority, item.sequence))
                    if self._prioritize
                    else (lambda item: item.sequence)
                ),
            )
            self._entries.remove(entry)
            self._condition.notify_all()
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

    async def drain(self) -> list[ReplyCandidate]:
        """Remove and return all queued candidates in deterministic order."""
        async with self._condition:
            entries = sorted(self._entries, key=lambda item: item.sequence)
            self._entries = []
            return [entry.candidate for entry in entries]

    async def close(self) -> None:
        """Wake waiting consumers and reject future candidates."""
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


ReplyProcessor = Callable[[ReplyCandidate], Awaitable[None]]
ReplyTerminalDropSink = Callable[[ReplyCandidate, str], None]


class ReplyWorker:
    """Process admitted replies serially while isolating item failures."""

    def __init__(
        self,
        *,
        queue: BoundedReplyQueue,
        processor: ReplyProcessor,
        metrics: ReplyMetrics,
        generation_id: int,
        max_message_age_seconds: float | None,
        clock: Callable[[], float] = time.time,
        terminal_drop_sink: ReplyTerminalDropSink | None = None,
    ) -> None:
        self._queue = queue
        self._processor = processor
        self._metrics = metrics
        self._generation_id = generation_id
        self._max_message_age_seconds = max_message_age_seconds
        self._clock = clock
        self._terminal_drop_sink = terminal_drop_sink

    async def run(self) -> None:
        """Run until the queue is closed and drained."""
        while True:
            candidate = await self._queue.get()
            self._metrics.queue_depth = self._queue.qsize
            if candidate is None:
                return
            if candidate.generation_id != self._generation_id:
                if candidate.media_turn is not None:
                    await candidate.media_turn.cancel()
                self._record_terminal_drop(candidate, "stale_generation")
                continue
            if (
                self._max_message_age_seconds is not None
                and self._clock() - candidate.message.timestamp > self._max_message_age_seconds
            ):
                if candidate.media_turn is not None:
                    await candidate.media_turn.cancel()
                self._record_terminal_drop(candidate, "expired")
                continue

            started_at = self._clock()
            self._metrics.queue_wait_seconds.append(max(0.0, started_at - candidate.admitted_at))
            succeeded = False
            for attempt in range(2):
                try:
                    await self._processor(candidate)
                    succeeded = True
                    break
                except asyncio.CancelledError:
                    if candidate.media_turn is not None:
                        await candidate.media_turn.cancel()
                    self._record_terminal_drop(candidate, "cancelled")
                    raise
                except Exception as exc:
                    media_started = (
                        candidate.media_turn is not None and candidate.media_turn.acquired
                    )
                    if attempt == 0 and not media_started:
                        self._metrics.reply_retries += 1
                        logger.warning(
                            "Retrying danmaku reply once: reply_id={} error_type={}",
                            candidate.reply_id,
                            type(exc).__name__,
                        )
                        continue
                    if candidate.media_turn is not None:
                        await candidate.media_turn.cancel()
                    self._metrics.reply_failure += 1
                    self._metrics.dropped["reply_failed"] += 1
                    logger.error(
                        "Danmaku reply processing failed after retry: reply_id={} error_type={}",
                        candidate.reply_id,
                        type(exc).__name__,
                    )
                    break
            if not succeeded:
                continue

            self._metrics.reply_success += 1
            self._metrics.reply_latency_seconds.append(
                max(0.0, self._clock() - started_at),
            )

    def _record_terminal_drop(self, candidate: ReplyCandidate, reason: str) -> None:
        self._metrics.dropped[reason] += 1
        self._metrics.admitted_dropped[reason] += 1
        if self._terminal_drop_sink is not None:
            self._terminal_drop_sink(candidate, reason)

    async def stop(self) -> None:
        """Stop after already queued items are drained."""
        await self._queue.close()


class DanmakuReplyRuntime:
    """Own admission, queue, worker, and metrics for one session generation."""

    def __init__(
        self,
        policy: ReplyPolicyConfig,
        processor: ReplyProcessor,
        terminal_drop_sink: ReplyTerminalDropSink | None = None,
    ) -> None:
        self._policy = policy
        self._processor = processor
        self._terminal_drop_sink = terminal_drop_sink
        self._admission = ReplyAdmissionController(policy)
        self._queue: BoundedReplyQueue | None = None
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._generation_id = 0
        self._submission_sequence = 0
        self._active_replies = 0
        self._media_coordinator = OrderedReplyMediaCoordinator()
        self._media_arbiter = BroadcastMediaArbiter()
        self.metrics = ReplyMetrics()

    @property
    def media_arbiter(self) -> BroadcastMediaArbiter:
        return self._media_arbiter

    @property
    def worker_running(self) -> bool:
        """Whether the generation's serialized reply worker is active."""
        return any(not task.done() for task in self._worker_tasks)

    @property
    def busy(self) -> bool:
        """Whether an admitted viewer reply is queued or currently processing."""
        return self._active_replies > 0 or bool(self._queue and self._queue.qsize)

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
        tasks = self._worker_tasks
        if queue is not None:
            for candidate in await queue.drain():
                if candidate.media_turn is not None:
                    await candidate.media_turn.cancel()
                self._record_terminal_drop(candidate, "stale_generation")
            await queue.close()
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._queue = None
        self._worker_tasks = []
        self._generation_id = generation_id
        self._submission_sequence = 0
        self._active_replies = 0
        self._media_coordinator = OrderedReplyMediaCoordinator()
        self.metrics.queue_depth = 0

    async def submit(
        self,
        message: DanmakuMessage,
        *,
        room_id: int,
        generation_id: int,
    ) -> ReplySubmissionResult:
        """Admit and enqueue one message for the current generation."""
        if generation_id != self._generation_id:
            self.metrics.dropped["stale_generation"] += 1
            return ReplySubmissionResult(admitted=False, reason="stale_generation")

        decision = self._admission.decide(message)
        if not decision.admitted or decision.priority is None:
            self.metrics.dropped[decision.reason or "rejected"] += 1
            return ReplySubmissionResult(
                admitted=False,
                reason=decision.reason or "rejected",
            )

        self._ensure_worker()
        assert self._queue is not None
        queue = self._queue
        candidate = ReplyCandidate(
            message=message,
            priority=decision.priority,
            generation_id=generation_id,
            admitted_at=time.time(),
            room_id=room_id,
            sequence=self._submission_sequence,
            media_turn=ReplyMediaTurn(
                self._media_coordinator,
                self._submission_sequence,
                BroadcastMediaTurn(
                    self._media_arbiter,
                    priority=20 + int(decision.priority),
                ),
            ),
        )
        self._submission_sequence += 1
        result = await (
            queue.put_wait(candidate) if self._policy.mode == "exhaustive" else queue.put(candidate)
        )
        if not result.accepted:
            if candidate.media_turn is not None:
                await candidate.media_turn.cancel()
            self.metrics.dropped[result.reason or "queue_rejected"] += 1
            return ReplySubmissionResult(
                admitted=False,
                reason=result.reason or "queue_rejected",
                priority=decision.priority,
            )
        self.metrics.admitted += 1
        if result.evicted is not None:
            if result.evicted.media_turn is not None:
                await result.evicted.media_turn.cancel()
            self._record_terminal_drop(result.evicted, "queue_evicted")
        self.metrics.queue_depth = queue.qsize
        self.metrics.max_queue_depth = max(
            self.metrics.max_queue_depth,
            queue.max_observed_size,
        )
        return ReplySubmissionResult(
            admitted=True,
            reason=result.reason,
            priority=decision.priority,
            evicted_lower_priority=result.evicted is not None,
            evicted_message=result.evicted.message if result.evicted is not None else None,
        )

    async def close(self) -> None:
        """Cancel all reply work and release owned queue resources."""
        queue = self._queue
        tasks = self._worker_tasks
        if queue is not None:
            for candidate in await queue.drain():
                if candidate.media_turn is not None:
                    await candidate.media_turn.cancel()
                self._record_terminal_drop(candidate, "cancelled")
            await queue.close()
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._queue = None
        self._worker_tasks = []
        self.metrics.queue_depth = 0

    def _ensure_worker(self) -> None:
        if self.worker_running:
            return
        if self._queue is not None:
            return
        self._queue = BoundedReplyQueue(
            self._policy.max_queue_size,
            prioritize=self._policy.mode != "exhaustive",
        )
        max_age = (
            None if self._policy.mode == "exhaustive" else self._policy.max_message_age_seconds
        )
        for index in range(self._policy.generation_concurrency):
            worker = ReplyWorker(
                queue=self._queue,
                processor=self._process_candidate,
                metrics=self.metrics,
                generation_id=self._generation_id,
                max_message_age_seconds=max_age,
                terminal_drop_sink=self._terminal_drop_sink,
            )
            self._worker_tasks.append(
                asyncio.create_task(
                    worker.run(),
                    name=f"bilibili-reply-{self._generation_id}-{index}",
                )
            )

    def _record_terminal_drop(self, candidate: ReplyCandidate, reason: str) -> None:
        self.metrics.dropped[reason] += 1
        self.metrics.admitted_dropped[reason] += 1
        if self._terminal_drop_sink is not None:
            self._terminal_drop_sink(candidate, reason)

    async def _process_candidate(self, candidate: ReplyCandidate) -> None:
        self._active_replies += 1
        try:
            await self._processor(candidate)
        finally:
            self._active_replies = max(0, self._active_replies - 1)
