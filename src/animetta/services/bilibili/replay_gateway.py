"""Deterministic, stoppable Gateway for normalized livestream event replay."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from loguru import logger

from .models import DanmakuMessage, LivestreamEvent


@dataclass(frozen=True, slots=True)
class BurstWindow:
    """A multiplier active for a fixed interval on the replay wall clock."""

    start_seconds: float
    duration_seconds: float
    multiplier: float

    def __post_init__(self) -> None:
        if self.start_seconds < 0:
            raise ValueError("burst start_seconds must be non-negative")
        if self.duration_seconds <= 0:
            raise ValueError("burst duration_seconds must be positive")
        if self.multiplier <= 0:
            raise ValueError("burst multiplier must be positive")


HIGH_HEAT_BURSTS = (
    BurstWindow(start_seconds=30 * 60, duration_seconds=60, multiplier=2),
    BurstWindow(start_seconds=60 * 60, duration_seconds=30, multiplier=3),
    BurstWindow(start_seconds=80 * 60, duration_seconds=120, multiplier=2),
)


class ReplayTimeline:
    """Map source offsets onto a continuous replay timeline."""

    def __init__(
        self,
        *,
        speed: float = 1.0,
        burst_windows: Sequence[BurstWindow] = (),
    ) -> None:
        if speed <= 0:
            raise ValueError("replay speed must be positive")
        self.speed = speed
        self.burst_windows = tuple(sorted(burst_windows, key=lambda window: window.start_seconds))
        previous_end = 0.0
        for window in self.burst_windows:
            if window.start_seconds < previous_end:
                raise ValueError("burst windows must not overlap")
            previous_end = window.start_seconds + window.duration_seconds

    def target_elapsed_seconds(self, offset_ms: int) -> float:
        """Return the replay-wall target for one source offset."""
        if offset_ms < 0:
            raise ValueError("event offset_ms must be non-negative")
        source_target = offset_ms / 1000
        source_cursor = 0.0
        wall_cursor = 0.0
        for window in self.burst_windows:
            base_wall = window.start_seconds - wall_cursor
            base_source = base_wall * self.speed
            if source_target <= source_cursor + base_source:
                return wall_cursor + (source_target - source_cursor) / self.speed
            source_cursor += base_source
            wall_cursor = window.start_seconds

            burst_source = window.duration_seconds * self.speed * window.multiplier
            if source_target <= source_cursor + burst_source:
                return wall_cursor + (source_target - source_cursor) / (
                    self.speed * window.multiplier
                )
            source_cursor += burst_source
            wall_cursor += window.duration_seconds
        return wall_cursor + (source_target - source_cursor) / self.speed

    def burst_profile(self, source_end_offset_ms: int) -> dict[str, object]:
        """Describe which configured wall-clock burst windows a source can complete."""
        end_target = self.target_elapsed_seconds(source_end_offset_ms)
        windows = [
            {
                "start_seconds": window.start_seconds,
                "duration_seconds": window.duration_seconds,
                "multiplier": window.multiplier,
                "reached": end_target >= window.start_seconds,
                "completed": end_target >= window.start_seconds + window.duration_seconds,
            }
            for window in self.burst_windows
        ]
        completed = sum(bool(window["completed"]) for window in windows)
        return {
            "configured": len(windows),
            "completed": completed,
            "all_completed": completed == len(windows),
            "source_end_offset_ms": source_end_offset_ms,
            "replay_end_seconds": round(end_target, 6),
            "windows": windows,
        }


@dataclass(slots=True)
class ReplayMetrics:
    """Scheduling and callback evidence collected by one replay."""

    scheduled: int = 0
    dispatched: int = 0
    callback_failures: int = 0
    stopped_early: bool = False
    burst_windows: tuple[BurstWindow, ...] = ()
    _last_target_elapsed_seconds: float = 0.0
    _burst_event_counts: list[int] = field(default_factory=list)
    _scheduling_lag_ms: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._burst_event_counts = [0 for _window in self.burst_windows]

    def record_scheduled(self, lag_ms: float, *, target_elapsed_seconds: float) -> None:
        self.scheduled += 1
        self._scheduling_lag_ms.append(max(0.0, lag_ms))
        self._last_target_elapsed_seconds = max(
            self._last_target_elapsed_seconds,
            target_elapsed_seconds,
        )
        for index, window in enumerate(self.burst_windows):
            if (
                window.start_seconds
                <= target_elapsed_seconds
                < window.start_seconds + window.duration_seconds
            ):
                self._burst_event_counts[index] += 1

    @property
    def scheduling_lag_p95_ms(self) -> float:
        return _percentile(self._scheduling_lag_ms, 0.95)

    @property
    def scheduling_lag_max_ms(self) -> float:
        return round(max(self._scheduling_lag_ms, default=0.0), 3)

    def to_dict(self) -> dict[str, object]:
        burst_windows = [
            {
                "start_seconds": window.start_seconds,
                "duration_seconds": window.duration_seconds,
                "multiplier": window.multiplier,
                "reached": self._last_target_elapsed_seconds >= window.start_seconds,
                "completed": self._last_target_elapsed_seconds
                >= window.start_seconds + window.duration_seconds,
                "scheduled_events": self._burst_event_counts[index],
            }
            for index, window in enumerate(self.burst_windows)
        ]
        completed_bursts = sum(bool(window["completed"]) for window in burst_windows)
        return {
            "scheduled": self.scheduled,
            "dispatched": self.dispatched,
            "callback_failures": self.callback_failures,
            "stopped_early": self.stopped_early,
            "scheduling_lag_p95_ms": self.scheduling_lag_p95_ms,
            "scheduling_lag_max_ms": self.scheduling_lag_max_ms,
            "burst_profile": {
                "configured": len(burst_windows),
                "completed": completed_bursts,
                "all_completed": completed_bursts == len(burst_windows),
                "replay_end_seconds": round(self._last_target_elapsed_seconds, 6),
                "windows": burst_windows,
            },
        }


class ReplayDanmakuGateway:
    """Replay normalized events behind the production DanmakuGateway contract."""

    def __init__(
        self,
        events: Sequence[LivestreamEvent],
        *,
        speed: float = 1.0,
        burst_windows: Sequence[BurstWindow] = (),
        monotonic: Callable[[], float] = time.monotonic,
        waiter: Callable[[float], bool] | None = None,
        shutdown_timeout_seconds: float = 5.0,
    ) -> None:
        self._events = tuple(events)
        self._validate_events()
        self._timeline = ReplayTimeline(speed=speed, burst_windows=burst_windows)
        self._monotonic = monotonic
        self._stop_event = threading.Event()
        self._waiter = waiter or self._stop_event.wait
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._event_callback: Callable[[LivestreamEvent], None] | None = None
        self._message_callback: Callable[[DanmakuMessage], None] | None = None
        self._status_callback: Callable[[bool, str], None] | None = None
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._running = False
        self.metrics = ReplayMetrics(burst_windows=self._timeline.burst_windows)

    def set_event_callback(
        self,
        callback: Callable[[LivestreamEvent], None],
    ) -> None:
        self._event_callback = callback

    def set_message_callback(
        self,
        callback: Callable[[DanmakuMessage], None],
    ) -> None:
        self._message_callback = callback

    def set_status_callback(
        self,
        callback: Callable[[bool, str], None],
    ) -> None:
        self._status_callback = callback

    def start(self) -> None:
        """Start one replay worker and return immediately."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self.metrics = ReplayMetrics(burst_windows=self._timeline.burst_windows)
            self._running = True
            self._thread = threading.Thread(
                target=self._run,
                name="bilibili-replay",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop idempotently and join the worker within the lifecycle bound."""
        self._stop_event.set()
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return
        thread.join(timeout=self._shutdown_timeout_seconds)
        if thread.is_alive():
            raise TimeoutError("replay gateway did not stop within five seconds")

    def wait_until_complete(self, timeout: float = 5.0) -> bool:
        """Wait for test/runner coordination without changing replay state."""
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return False
        thread.join(timeout=timeout)
        return not thread.is_alive()

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    @property
    def thread_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def pending_callback_count(self) -> int:
        """Callbacks execute synchronously on the worker; none may remain queued."""
        return 0

    def _run(self) -> None:
        started = self._monotonic()
        self._notify_status(True, "Replay connected")
        completed = False
        try:
            for event in self._events:
                if self._stop_event.is_set():
                    break
                target = self._timeline.target_elapsed_seconds(event.offset_ms)
                if not self._wait_until(started + target):
                    break
                elapsed = self._monotonic() - started
                self.metrics.record_scheduled(
                    (elapsed - target) * 1000,
                    target_elapsed_seconds=target,
                )
                self._dispatch(event)
            else:
                completed = True
        finally:
            self.metrics.stopped_early = not completed
            with self._state_lock:
                self._running = False
            self._notify_status(False, "Replay complete" if completed else "Replay stopped")

    def _wait_until(self, deadline: float) -> bool:
        while not self._stop_event.is_set():
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return True
            if self._waiter(remaining):
                return False
        return False

    def _dispatch(self, event: LivestreamEvent) -> None:
        try:
            if self._event_callback is not None:
                self._event_callback(event)
            elif self._message_callback is not None:
                message = event.to_danmaku_message()
                if message is None:
                    return
                self._message_callback(message)
            self.metrics.dispatched += 1
        except Exception as exc:
            self.metrics.callback_failures += 1
            logger.error(
                "Replay callback failed: error_type={}",
                type(exc).__name__,
            )

    def _notify_status(self, connected: bool, message: str) -> None:
        if self._status_callback is None:
            return
        try:
            self._status_callback(connected, message)
        except Exception as exc:
            logger.error(
                "Replay status callback failed: error_type={}",
                type(exc).__name__,
            )

    def _validate_events(self) -> None:
        for index, event in enumerate(self._events):
            if event.sequence != index:
                raise ValueError("replay events must have contiguous sequence numbers")
            if event.offset_ms < 0 or (
                index > 0 and event.offset_ms < self._events[index - 1].offset_ms
            ):
                raise ValueError("replay event timeline must be monotonic")


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 3)
