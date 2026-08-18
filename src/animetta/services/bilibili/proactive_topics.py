"""Generation-scoped scheduling and source selection for proactive host remarks."""

from __future__ import annotations

import asyncio
import random
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import uuid4

from loguru import logger

from animetta.config import ProactiveTopicsConfig
from animetta.services.bilibili.response_policy import normalize_proactive_topic_text
from animetta.services.scene_analysis.models import LiveSceneState, Trend

TopicSeedKind = Literal["scene", "deadpan_logic", "approved_meme"]


@dataclass(frozen=True, slots=True)
class TopicSeed:
    """One bounded prompt seed selected without performing network I/O."""

    kind: TopicSeedKind
    subject: str | None
    dedupe_key: str | None
    provenance: str


@dataclass(frozen=True, slots=True)
class TopicContext:
    """Read-only inputs available to every topic source."""

    scene: LiveSceneState | None
    used_dedupe_keys: frozenset[str]
    recent_outputs: tuple[str, ...]


class TopicSource(Protocol):
    """Extension boundary for scene, deadpan, or future approved-meme seeds."""

    async def next_seed(self, context: TopicContext) -> TopicSeed | None: ...


class SceneTopicSource:
    """Select the hottest fresh topic from the current scene snapshot."""

    _TREND_PRIORITY = {Trend.FALLING: 0, Trend.STABLE: 1, Trend.RISING: 2}

    async def next_seed(self, context: TopicContext) -> TopicSeed | None:
        if context.scene is None:
            return None
        candidates = []
        for topic in context.scene.topics:
            key = f"scene:{topic.label}:{topic.last_event_seq}"
            if key not in context.used_dedupe_keys:
                candidates.append((topic, key))
        if not candidates:
            return None
        topic, key = max(
            candidates,
            key=lambda item: (
                item[0].heat,
                self._TREND_PRIORITY[item[0].trend],
                item[0].last_event_seq,
                item[0].label,
            ),
        )
        return TopicSeed(
            kind="scene",
            subject=topic.label,
            dedupe_key=key,
            provenance="scene_runtime",
        )


class DeadpanLogicSource:
    """Fall back to an unconstrained subject while preserving the style contract."""

    async def next_seed(self, context: TopicContext) -> TopicSeed:
        del context
        return TopicSeed(
            kind="deadpan_logic",
            subject=None,
            dedupe_key=None,
            provenance="deadpan_logic",
        )


@dataclass(slots=True)
class ProactiveTopicMetrics:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    skipped_busy: int = 0
    activity_resets: int = 0


TopicProcessor = Callable[
    [TopicSeed, str, int, int, tuple[str, ...]],
    Awaitable[str],
]
InterruptSink = Callable[[str], Awaitable[None]]
SceneSnapshot = Callable[[], LiveSceneState | None]
BusyCheck = Callable[[], bool]
Sleep = Callable[[float], Awaitable[None]]
IntervalPicker = Callable[[float, float], float]
IdFactory = Callable[[], str]


class ProactiveTopicRuntime:
    """Own one resettable proactive timer for the authoritative live generation."""

    RECENT_OUTPUT_LIMIT = 8

    def __init__(
        self,
        config: ProactiveTopicsConfig,
        processor: TopicProcessor,
        interrupt_sink: InterruptSink,
        *,
        scene_snapshot: SceneSnapshot = lambda: None,
        busy: BusyCheck = lambda: False,
        sources: Sequence[TopicSource] | None = None,
        sleep: Sleep = asyncio.sleep,
        interval_picker: IntervalPicker = random.uniform,
        id_factory: IdFactory = lambda: str(uuid4()),
    ) -> None:
        self._config = config
        self._processor = processor
        self._interrupt_sink = interrupt_sink
        self._scene_snapshot = scene_snapshot
        self._busy = busy
        self._sources = tuple(sources or (SceneTopicSource(), DeadpanLogicSource()))
        self._sleep = sleep
        self._interval_picker = interval_picker
        self._id_factory = id_factory
        self._identity: tuple[int, int] | None = None
        self._active = False
        self._epoch = 0
        self._task: asyncio.Task[None] | None = None
        self._current_task_id: str | None = None
        self._playing_task_id: str | None = None
        self._used_dedupe_keys: set[str] = set()
        self._recent_outputs: deque[str] = deque(maxlen=self.RECENT_OUTPUT_LIMIT)
        self._transition_lock = asyncio.Lock()
        self.metrics = ProactiveTopicMetrics()

    @property
    def current_task_id(self) -> str | None:
        return self._current_task_id or self._playing_task_id

    @property
    def recent_outputs(self) -> tuple[str, ...]:
        return tuple(self._recent_outputs)

    def configure(self, config: ProactiveTopicsConfig) -> None:
        """Replace startup-owned controls without constructing a second runtime."""
        self._config = config
        if not config.enabled:
            self._active = False
            self._epoch += 1
            if self._task is not None and not self._task.done():
                self._task.cancel()
            self._task = None
            self._current_task_id = None

    async def update_status(self, payload: dict[str, object]) -> None:
        """Arm only for an authoritative ``live`` snapshot."""
        state = str(payload.get("state") or "")
        room_value = payload.get("room_id") or payload.get("desired_room_id")
        generation_value = payload.get("generation_id")
        identity = (
            (int(room_value), int(generation_value))
            if isinstance(room_value, int)
            and not isinstance(room_value, bool)
            and room_value > 0
            and isinstance(generation_value, int)
            and not isinstance(generation_value, bool)
            and generation_value >= 0
            else None
        )
        async with self._transition_lock:
            if not self._config.enabled or state != "live" or identity is None:
                await self._cancel_owned(interrupt=True)
                self._active = False
                return
            if identity != self._identity:
                await self._cancel_owned(interrupt=True)
                self._identity = identity
                self._used_dedupe_keys.clear()
                self._recent_outputs.clear()
            if self._active:
                return
            self._active = True
            self._epoch += 1
            self._arm(self._config.initial_silence_seconds, self._epoch, identity)

    async def notify_activity(self) -> None:
        """Interrupt autonomous work and begin a fresh first-silence window."""
        async with self._transition_lock:
            if not self._active or self._identity is None:
                return
            identity = self._identity
            await self._cancel_owned(interrupt=True)
            self.metrics.activity_resets += 1
            self._epoch += 1
            self._arm(self._config.initial_silence_seconds, self._epoch, identity)

    async def reset_after_viewer_reply(self) -> None:
        """Start the silence window after the admitted viewer reply has completed."""
        async with self._transition_lock:
            if not self._active or self._identity is None:
                return
            identity = self._identity
            await self._cancel_owned(interrupt=False)
            self._epoch += 1
            self._arm(self._config.initial_silence_seconds, self._epoch, identity)

    async def close(self) -> None:
        async with self._transition_lock:
            self._active = False
            await self._cancel_owned(interrupt=True)

    async def _cancel_owned(self, *, interrupt: bool) -> None:
        self._epoch += 1
        task = self._task
        self._task = None
        task_ids = tuple(
            dict.fromkeys(
                task_id for task_id in (self._current_task_id, self._playing_task_id) if task_id
            )
        )
        self._current_task_id = None
        if interrupt:
            self._playing_task_id = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        if interrupt:
            for task_id in task_ids:
                try:
                    await self._interrupt_sink(task_id)
                except Exception as exc:
                    logger.warning(
                        "Proactive topic interruption failed: error_type={}",
                        type(exc).__name__,
                    )
        if task is not None and task is not asyncio.current_task() and not task.done():
            await asyncio.gather(task, return_exceptions=True)

    def _arm(self, delay: float, epoch: int, identity: tuple[int, int]) -> None:
        self._task = asyncio.create_task(
            self._run_after(delay, epoch, identity),
            name=f"bilibili-proactive-topic-{identity[1]}",
        )

    async def _run_after(
        self,
        delay: float,
        epoch: int,
        identity: tuple[int, int],
    ) -> None:
        try:
            await self._sleep(delay)
            if not self._is_current(epoch, identity):
                return
            if self._busy():
                self.metrics.skipped_busy += 1
                self._arm(self._config.initial_silence_seconds, epoch, identity)
                return
            context = TopicContext(
                scene=self._scene_snapshot(),
                used_dedupe_keys=frozenset(self._used_dedupe_keys),
                recent_outputs=tuple(self._recent_outputs),
            )
            seed = await self._next_seed(context)
            if seed is None or not self._is_current(epoch, identity):
                self.metrics.failed += 1
                self._arm_next(epoch, identity)
                return
            if seed.dedupe_key:
                self._used_dedupe_keys.add(seed.dedupe_key)
            task_id = self._id_factory()
            self._current_task_id = task_id
            self._playing_task_id = None
            self.metrics.attempted += 1
            generation_failed = False
            try:
                response = await self._processor(
                    seed,
                    task_id,
                    identity[0],
                    identity[1],
                    tuple(self._recent_outputs),
                )
            except asyncio.CancelledError:
                self.metrics.cancelled += 1
                raise
            except Exception as exc:
                generation_failed = True
                self.metrics.failed += 1
                logger.warning(
                    "Proactive topic generation failed: error_type={}",
                    type(exc).__name__,
                )
                response = ""
            finally:
                if self._current_task_id == task_id:
                    self._current_task_id = None
            if not self._is_current(epoch, identity):
                return
            normalized = normalize_proactive_topic_text(response)
            if normalized:
                self._recent_outputs.append(normalized)
                self._playing_task_id = task_id
                self.metrics.succeeded += 1
            elif not generation_failed:
                self.metrics.failed += 1
            self._arm_next(epoch, identity)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.metrics.failed += 1
            logger.warning(
                "Proactive topic scheduling failed: error_type={}",
                type(exc).__name__,
            )
            if self._is_current(epoch, identity):
                self._arm_next(epoch, identity)

    async def _next_seed(self, context: TopicContext) -> TopicSeed | None:
        for source in self._sources:
            seed = await source.next_seed(context)
            if seed is not None:
                return seed
        return None

    def _arm_next(self, epoch: int, identity: tuple[int, int]) -> None:
        delay = self._interval_picker(
            self._config.interval_min_seconds,
            self._config.interval_max_seconds,
        )
        self._arm(delay, epoch, identity)

    def _is_current(self, epoch: int, identity: tuple[int, int]) -> bool:
        return self._active and epoch == self._epoch and identity == self._identity
