"""Room-owned cached runtime for livestream scene analysis."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Literal, Protocol

from loguru import logger

from animetta.config.scene_analysis import SceneAnalysisConfig

from .evidence import SceneEvidenceBuilder
from .guidance import GuidanceComposer, MemeRetriever, TechniqueRetriever
from .model_gateway import SceneModelGatewayError
from .models import (
    LiveSceneState,
    NormalizedSceneEvent,
    SceneEventType,
    SceneEvidence,
    SceneGuidance,
    SceneStatePatch,
)
from .reducer import SceneStateReducer, StaleScenePatchError

SceneAnalysisMode = Literal["off", "shadow", "active"]


class SceneGateway(Protocol):
    async def reflect(
        self,
        evidence: SceneEvidence,
        state: LiveSceneState,
    ) -> SceneStatePatch: ...


@dataclass
class SceneRuntimeMetrics:
    observed_events: int = 0
    stale_events: int = 0
    reflection_calls: int = 0
    reflection_successes: int = 0
    reflection_failures: int = 0
    coalesced_triggers: int = 0
    rate_limited_triggers: int = 0
    guidance_cache_hits: int = 0
    guidance_cache_misses: int = 0
    guidance_wait_timeouts: int = 0


class SceneRuntime:
    """Own transient scene state for one room generation outside LangGraph."""

    def __init__(
        self,
        *,
        session_id: str,
        room_id: int,
        generation_id: int,
        gateway: SceneGateway | None = None,
        mode: SceneAnalysisMode = "shadow",
        reflection_interval_seconds: float = 30.0,
        event_threshold: int = 30,
        max_reflections_per_minute: int = 4,
        guidance_wait_seconds: float = 0.3,
        clock: Callable[[], float] = time.time,
        technique_retriever: TechniqueRetriever | None = None,
        meme_retriever: MemeRetriever | None = None,
    ) -> None:
        if mode not in {"off", "shadow", "active"}:
            raise ValueError(f"unsupported scene analysis mode: {mode}")
        self._session_id = session_id
        self._room_id = room_id
        self._generation_id = generation_id
        self._gateway = gateway
        self._mode = mode
        self._reflection_interval_seconds = reflection_interval_seconds
        self._event_threshold = event_threshold
        self._max_reflections_per_minute = max_reflections_per_minute
        self._guidance_wait_seconds = guidance_wait_seconds
        self._clock = clock
        self._events: deque[NormalizedSceneEvent] = deque(maxlen=600)
        now = clock()
        self._state = LiveSceneState.initial(
            session_id=session_id,
            room_id=room_id,
            generation_id=generation_id,
            now=now,
        )
        self._latest_guidance: SceneGuidance | None = None
        self._last_reflection_at = now
        self._reflection_times: deque[float] = deque()
        self._refresh_task: asyncio.Task[None] | None = None
        self._refresh_pending = False
        self._deferred_trigger = False
        self._epoch = 0
        self._evidence_builder = SceneEvidenceBuilder()
        self._composer = GuidanceComposer(
            technique_retriever=technique_retriever,
            meme_retriever=meme_retriever,
        )
        self.metrics = SceneRuntimeMetrics()

    @property
    def mode(self) -> SceneAnalysisMode:
        return self._mode

    @property
    def latest_guidance(self) -> SceneGuidance | None:
        return self._latest_guidance

    @property
    def event_count(self) -> int:
        return len(self._events)

    def snapshot(self) -> LiveSceneState:
        return self._state.model_copy(deep=True)

    def bind_gateway(self, gateway: SceneGateway | None) -> None:
        """Bind the already-loaded profile LLM gateway without adding a service slot."""
        self._gateway = gateway
        if gateway is not None and self._deferred_trigger and self._mode != "off":
            self._deferred_trigger = False
            self._schedule_reflection()

    def set_mode(self, mode: SceneAnalysisMode) -> None:
        if mode not in {"off", "shadow", "active"}:
            raise ValueError(f"unsupported scene analysis mode: {mode}")
        self._mode = mode

    def configure(self, config: SceneAnalysisConfig) -> None:
        """Apply lightweight runtime controls without replacing room state."""
        self._mode = config.mode
        self._reflection_interval_seconds = config.reflection_interval_seconds
        self._event_threshold = config.event_threshold
        self._max_reflections_per_minute = config.max_reflections_per_minute
        self._guidance_wait_seconds = config.guidance_wait_seconds
        if config.mode == "off":
            self._refresh_pending = False
            if self._refresh_task is not None and not self._refresh_task.done():
                self._refresh_task.cancel()
            return
        if self._gateway is not None and self._deferred_trigger:
            self._deferred_trigger = False
            self._schedule_reflection()

    async def observe(self, event: NormalizedSceneEvent) -> bool:
        """Record every normalized room event before reply admission."""
        if (
            event.session_id != self._session_id
            or event.room_id != self._room_id
            or event.generation_id != self._generation_id
        ):
            self.metrics.stale_events += 1
            return False
        self._events.append(event)
        self.metrics.observed_events += 1
        if self._mode == "off":
            return True

        unconsumed = event.event_seq - self._state.last_event_seq
        elapsed = self._clock() - self._last_reflection_at
        if (
            event.critical
            or unconsumed >= self._event_threshold
            or elapsed >= self._reflection_interval_seconds
        ):
            self._schedule_reflection()
        return True

    async def observe_danmaku(
        self,
        message: object,
        *,
        room_id: int,
        generation_id: int,
    ) -> bool:
        """Normalize one Bilibili message and record it before reply admission."""
        next_seq = (
            self._events[-1].event_seq + 1 if self._events else self._state.last_event_seq + 1
        )
        is_super_chat = bool(getattr(message, "is_super_chat", False))
        is_gift = bool(getattr(message, "is_gift", False))
        metadata = getattr(message, "meta", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        amount_value = metadata.get("price", metadata.get("amount"))
        try:
            amount = float(amount_value) if amount_value is not None else None
        except (TypeError, ValueError):
            amount = None
        event_type = (
            SceneEventType.SUPER_CHAT
            if is_super_chat
            else SceneEventType.GIFT
            if is_gift
            else SceneEventType.DANMAKU
        )
        critical = is_super_chat or bool(is_gift and amount is not None and amount >= 100)
        actor_value = getattr(message, "user_id", 0)
        actor_id = str(actor_value) if actor_value else None
        return await self.observe(
            NormalizedSceneEvent(
                event_id=f"bilibili-{generation_id}-{next_seq}",
                event_seq=next_seq,
                session_id=self._session_id,
                room_id=room_id,
                generation_id=generation_id,
                occurred_at=float(getattr(message, "timestamp", self._clock())),
                event_type=event_type,
                actor_id=actor_id,
                actor_name=str(getattr(message, "user_name", ""))[:80] or None,
                text=str(getattr(message, "text", ""))[:500],
                amount=amount,
                critical=critical,
            )
        )

    async def record_host_reply(self, text: str, *, occurred_at: float | None = None) -> None:
        next_seq = (
            self._events[-1].event_seq + 1 if self._events else self._state.last_event_seq + 1
        )
        await self.observe(
            NormalizedSceneEvent(
                event_id=f"host-{self._generation_id}-{next_seq}",
                event_seq=next_seq,
                session_id=self._session_id,
                room_id=self._room_id,
                generation_id=self._generation_id,
                occurred_at=self._clock() if occurred_at is None else occurred_at,
                event_type=SceneEventType.HOST_REPLY,
                actor_id="host",
                text=text[:500],
            )
        )

    async def guidance_for_reply(self) -> SceneGuidance | None:
        """Return active guidance, waiting briefly only for an in-flight refresh."""
        if self._mode != "active":
            return None
        timeout_reason: list[str] = []
        task = self._refresh_task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=self._guidance_wait_seconds)
            except TimeoutError:
                self.metrics.guidance_wait_timeouts += 1
                timeout_reason.append("refresh_timeout")

        now = self._clock()
        if (
            self._latest_guidance is not None
            and not self._latest_guidance.is_expired(now)
            and not timeout_reason
        ):
            self.metrics.guidance_cache_hits += 1
            return self._latest_guidance

        self.metrics.guidance_cache_misses += 1
        reasons = timeout_reason
        if self._latest_guidance is not None and self._latest_guidance.is_expired(now):
            reasons.append("cache_expired")
        elif self._latest_guidance is None and not reasons:
            reasons.append("cache_empty")
        evidence = self._evidence_builder.build(
            list(self._events),
            after_event_seq=self._state.last_event_seq,
        )
        return self._composer.compose(
            self._state,
            evidence,
            now=now,
            extra_degradation_reasons=reasons,
        )

    async def switch_generation(self, *, room_id: int, generation_id: int) -> None:
        """Cancel old work and reset all transient room state."""
        self._epoch += 1
        task = self._refresh_task
        self._refresh_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._room_id = room_id
        self._generation_id = generation_id
        self._events.clear()
        self._reflection_times.clear()
        self._latest_guidance = None
        self._refresh_pending = False
        self._deferred_trigger = False
        now = self._clock()
        self._last_reflection_at = now
        self._state = LiveSceneState.initial(
            session_id=self._session_id,
            room_id=room_id,
            generation_id=generation_id,
            now=now,
        )

    async def wait_idle(self) -> None:
        task = self._refresh_task
        if task is None:
            return
        with suppress(asyncio.CancelledError):
            await asyncio.shield(task)

    def _schedule_reflection(self) -> None:
        if self._gateway is None:
            self._deferred_trigger = True
            return
        if self._refresh_task is not None and not self._refresh_task.done():
            self.metrics.coalesced_triggers += 1
            self._refresh_pending = True
            return
        now = self._clock()
        while self._reflection_times and self._reflection_times[0] <= now - 60:
            self._reflection_times.popleft()
        if len(self._reflection_times) >= self._max_reflections_per_minute:
            self.metrics.rate_limited_triggers += 1
            return
        epoch = self._epoch
        self._refresh_task = asyncio.create_task(self._run_reflection(epoch))

    async def _run_reflection(self, epoch: int) -> None:
        while True:
            # Triggers queued before this coroutine starts are already represented
            # in the evidence snapshot below. Only triggers arriving during the
            # model call need one follow-up pass.
            self._refresh_pending = False
            state = self._state
            evidence = self._evidence_builder.build(
                list(self._events),
                after_event_seq=state.last_event_seq,
            )
            if evidence is None:
                return
            now = self._clock()
            while self._reflection_times and self._reflection_times[0] <= now - 60:
                self._reflection_times.popleft()
            if len(self._reflection_times) >= self._max_reflections_per_minute:
                self.metrics.rate_limited_triggers += 1
                return
            self._reflection_times.append(now)
            self._last_reflection_at = now
            self.metrics.reflection_calls += 1
            if self._gateway is None:
                self._record_failure("model_unavailable")
                return
            try:
                patch = await self._gateway.reflect(evidence, state)
                if epoch != self._epoch or state.state_revision != self._state.state_revision:
                    return
                self._state = SceneStateReducer.apply(self._state, patch)
            except SceneModelGatewayError as exc:
                self._record_failure(exc.code)
                return
            except StaleScenePatchError:
                self._record_failure("stale_patch")
                return
            except Exception:
                logger.exception("Scene reflection failed")
                self._record_failure("runtime_error")
                return

            self.metrics.reflection_successes += 1
            self._latest_guidance = self._composer.compose(
                self._state,
                evidence,
                now=self._clock(),
            )
            logger.info(
                "Scene reflection completed: room_id={} generation_id={} revision={} events={}",
                self._room_id,
                self._generation_id,
                self._state.state_revision,
                evidence.metrics.event_count,
            )
            if not self._refresh_pending:
                return

    def _record_failure(self, code: str) -> None:
        self.metrics.reflection_failures += 1
        now = self._clock()
        self._state = SceneStateReducer.degrade(
            self._state,
            reasons=[code],
            now=now,
        )
        evidence = self._evidence_builder.build(
            list(self._events),
            after_event_seq=self._state.last_event_seq,
        )
        self._latest_guidance = self._composer.compose(
            self._state,
            evidence,
            now=now,
        )
        logger.warning(
            "Scene reflection degraded: room_id={} generation_id={} reason={}",
            self._room_id,
            self._generation_id,
            code,
        )
