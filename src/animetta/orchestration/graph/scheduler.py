"""Lightweight asyncio-based periodic task scheduler.

Provides AsyncScheduler with configurable intervals, timeout protection, and metrics logging.
Designed for PeriodicLearner, MemePool maintenance, and other background tasks.

Usage:
    scheduler = AsyncScheduler()
    scheduler.add_task("my_task", my_async_func, interval=3600, timeout=300)
    await scheduler.start()
    ...
    await scheduler.stop()
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

# AsyncCallable was added provisionally in Python 3.12 typing but may be absent
# in some builds. Define an equivalent type alias.
AsyncCallable = Callable[..., Coroutine[Any, Any, Any]]

import contextlib

from loguru import logger

_MIN_DURATION_SECONDS = 1e-9


def _elapsed_since(start: float) -> float:
    return max(time.monotonic() - start, _MIN_DURATION_SECONDS)


@dataclass
class TaskMetrics:
    """Per-task execution metrics."""

    name: str
    last_run: float | None = None  # timestamp
    last_duration: float | None = None  # seconds
    success_count: int = 0
    failure_count: int = 0
    total_runs: int = 0


@dataclass
class ScheduledTask:
    """A registered scheduled task."""

    name: str
    func: AsyncCallable[[], Any]
    interval: float  # seconds
    timeout: float  # max execution time
    metrics: TaskMetrics = field(default_factory=lambda: TaskMetrics(name=""))
    _task: asyncio.Task | None = None
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        self.metrics.name = self.name


class AsyncScheduler:
    """Lightweight asyncio-based periodic task scheduler.

    Features:
    - Add/remove tasks at runtime
    - Per-task configurable interval and timeout
    - Timeout protection (cancels hung tasks)
    - Metrics logging per task
    - Graceful shutdown
    """

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._main_loop_task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────

    def add_task(
        self,
        name: str,
        func: AsyncCallable[[], Any],
        *,
        interval: float,
        timeout: float = 300,
    ) -> None:
        """Register a periodic task.

        Args:
            name: Unique task identifier.
            func: Async callable (no arguments).
            interval: Interval in seconds between runs.
            timeout: Maximum execution time per run (default 300s).
        """
        if name in self._tasks:
            logger.warning(f"[Scheduler] Task '{name}' already registered, replacing")
        self._tasks[name] = ScheduledTask(
            name=name,
            func=func,
            interval=interval,
            timeout=timeout,
        )
        logger.info(
            f"[Scheduler] Task '{name}' registered (interval={interval}s, timeout={timeout}s)"
        )

    def remove_task(self, name: str) -> None:
        """Remove and cancel a registered task."""
        task = self._tasks.pop(name, None)
        if task and task._task and not task._task.done():
            task._cancel_event.set()
            task._task.cancel()
            logger.info(f"[Scheduler] Task '{name}' removed and cancelled")
        elif task:
            logger.info(f"[Scheduler] Task '{name}' removed")
        else:
            logger.warning(f"[Scheduler] Task '{name}' not found")

    async def start(self) -> None:
        """Start the scheduler main loop."""
        if self._running:
            logger.warning("[Scheduler] Already running")
            return
        self._running = True
        self._main_loop_task = asyncio.create_task(self._run_loop())
        logger.info(f"[Scheduler] Started with {len(self._tasks)} task(s)")

    async def stop(self) -> None:
        """Gracefully stop all tasks and the main loop."""
        self._running = False

        # Signal cancellation to all task loops
        for task in self._tasks.values():
            task._cancel_event.set()
            if task._task and not task._task.done():
                task._task.cancel()

        # Cancel main loop
        if self._main_loop_task and not self._main_loop_task.done():
            self._main_loop_task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._main_loop_task, timeout=10)

        logger.info("[Scheduler] Stopped")

    # ── Metrics ────────────────────────────────────────────

    def get_metrics(self) -> list[TaskMetrics]:
        """Return metrics for all registered tasks."""
        return [t.metrics for t in self._tasks.values()]

    def get_task_metrics(self, name: str) -> TaskMetrics | None:
        """Return metrics for a specific task."""
        task = self._tasks.get(name)
        return task.metrics if task else None

    # ── Main loop ─────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main scheduler loop — runs each task on its own interval."""
        if not self._tasks:
            logger.info("[Scheduler] No tasks registered, waiting for additions")
            # Keep alive but idle
            try:
                while self._running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            return

        # Start per-task execution loops concurrently
        task_loops = [
            asyncio.create_task(self._run_task_loop(task)) for task in self._tasks.values()
        ]

        try:
            # Wait until stopped
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            for tl in task_loops:
                if not tl.done():
                    tl.cancel()
            await asyncio.gather(*task_loops, return_exceptions=True)

    async def _run_task_loop(self, task: ScheduledTask) -> None:
        """Execute a single task on its interval loop with timeout protection."""
        # Initial delay: stagger tasks so they don't all fire at once
        # Use hash of task name for deterministic but distributed start times
        import hashlib

        delay_hash = int(hashlib.md5(task.name.encode()).hexdigest()[:8], 16)
        initial_delay = (delay_hash % 60) / 60.0 * min(task.interval, 60)
        await asyncio.sleep(initial_delay)

        while self._running and not task._cancel_event.is_set():
            try:
                await self._execute_with_timeout(task)
            except Exception as e:
                logger.error(f"[Scheduler] Task '{task.name}' execution error: {e}")
                task.metrics.failure_count += 1

            # Wait for interval (checking cancel each second)
            waited = 0.0
            while waited < task.interval and self._running and not task._cancel_event.is_set():
                await asyncio.sleep(1)
                waited += 1

    async def _execute_with_timeout(self, task: ScheduledTask) -> None:
        """Execute a single task run with timeout protection."""
        start = time.monotonic()
        task.metrics.total_runs += 1

        try:
            await asyncio.wait_for(task.func(), timeout=task.timeout)
            elapsed = _elapsed_since(start)
            task.metrics.last_run = time.time()
            task.metrics.last_duration = elapsed
            task.metrics.success_count += 1
            logger.info(
                f"[Scheduler] Task '{task.name}' completed in {elapsed:.1f}s "
                f"(success={task.metrics.success_count}, failure={task.metrics.failure_count})"
            )
        except TimeoutError:
            elapsed = _elapsed_since(start)
            logger.warning(
                f"[Scheduler] Task '{task.name}' timed out after {elapsed:.1f}s "
                f"(timeout={task.timeout}s)"
            )
            task.metrics.failure_count += 1
        except asyncio.CancelledError:
            logger.info(f"[Scheduler] Task '{task.name}' was cancelled")
            raise
