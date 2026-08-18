"""Single-owner runtime for the Bilibili livestream connection."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Protocol, cast

from loguru import logger

from animetta.config import ReplyPolicyConfig

from .danmaku_buffer import DanmakuBuffer
from .gateway import DanmakuGateway, create_danmaku_gateway
from .livestream_state import LivestreamSnapshot, LivestreamState
from .models import (
    DanmakuMessage,
    LivestreamEvent,
    LivestreamEventMetrics,
    LivestreamEventType,
)
from .reply_queue import DanmakuReplyRuntime, ReplyMetrics, ReplySubmissionResult

GatewayFactory = Callable[[int, str], DanmakuGateway]
StatusSink = Callable[[dict[str, object]], Awaitable[None]]
RawMessageSink = Callable[[DanmakuMessage, int], Awaitable[None]]
RawEventSink = Callable[[LivestreamEvent, int, int], Awaitable[None]]
CandidateSink = Callable[[DanmakuMessage, int, int], Awaitable[None]]
ReplyDecisionSink = Callable[
    [DanmakuMessage, ReplySubmissionResult, int],
    Awaitable[None],
]


class LivestreamSceneRuntime(Protocol):
    async def switch_generation(self, *, room_id: int, generation_id: int) -> None: ...

    async def observe_danmaku(
        self,
        message: DanmakuMessage,
        *,
        room_id: int,
        generation_id: int,
    ) -> object: ...


async def _discard_status(_payload: dict[str, object]) -> None:
    return None


async def _discard_message(_message: DanmakuMessage, _room_id: int) -> None:
    return None


async def _discard_event(
    _event: LivestreamEvent,
    _room_id: int,
    _generation_id: int,
) -> None:
    return None


async def _discard_candidate(
    _message: DanmakuMessage,
    _room_id: int,
    _generation_id: int,
) -> None:
    return None


async def _discard_reply_decision(
    _message: DanmakuMessage,
    _result: ReplySubmissionResult,
    _room_id: int,
) -> None:
    return None


class StaleGenerationError(RuntimeError):
    """Reject a control command based on an outdated session snapshot."""


class LivestreamSession:
    """Own exactly one Bilibili gateway and its public lifecycle state."""

    def __init__(
        self,
        gateway_factory: GatewayFactory = create_danmaku_gateway,
        status_sink: StatusSink = _discard_status,
        raw_event_sink: RawEventSink = _discard_event,
        raw_message_sink: RawMessageSink = _discard_message,
        candidate_sink: CandidateSink = _discard_candidate,
        reply_decision_sink: ReplyDecisionSink = _discard_reply_decision,
        reply_runtime: DanmakuReplyRuntime | None = None,
        scene_runtime: LivestreamSceneRuntime | None = None,
        buffer: DanmakuBuffer | None = None,
        shutdown_timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._gateway_factory = gateway_factory
        self._status_sink = status_sink
        self._raw_event_sink = raw_event_sink
        self._raw_message_sink = raw_message_sink
        self._candidate_sink = candidate_sink
        self._reply_decision_sink = reply_decision_sink
        self._reply_runtime = reply_runtime
        self._scene_runtime = scene_runtime
        self._buffer = buffer
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._clock = clock

        self._lock = asyncio.Lock()
        self._gateway: DanmakuGateway | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._snapshot = LivestreamSnapshot.initial()
        self._callback_tasks: set[asyncio.Task[None]] = set()
        self._metrics = reply_runtime.metrics if reply_runtime else ReplyMetrics()
        self._event_metrics = LivestreamEventMetrics()

    @property
    def metrics(self) -> ReplyMetrics:
        """Expose read-only access to session-owned runtime counters."""
        return self._metrics

    @property
    def event_metrics(self) -> LivestreamEventMetrics:
        """Expose transport-event counters without changing reply metrics."""
        return self._event_metrics

    @property
    def callback_task_count(self) -> int:
        """Return the number of callback tasks currently owned by the session."""
        return len(self._callback_tasks)

    @property
    def reply_busy(self) -> bool:
        """Whether the viewer reply pipeline currently owns pending work."""
        return bool(self._reply_runtime and self._reply_runtime.busy)

    def configure_reply_policy(self, policy: ReplyPolicyConfig) -> None:
        """Configure the reply runtime before it becomes active."""
        if self._reply_runtime is not None:
            self._reply_runtime.configure(policy)

    def snapshot(self) -> dict[str, Any]:
        """Return a detached, credential-free view of current state."""
        return self._snapshot.to_dict()

    async def set_room(
        self,
        room_id: int,
        sessdata: str = "",
        *,
        expected_generation_id: int | None = None,
    ) -> dict[str, Any]:
        """Start or hot-switch to ``room_id`` without blocking the event loop."""
        if room_id <= 0:
            raise ValueError("room_id must be a positive integer")

        async with self._lock:
            self._ensure_expected_generation(expected_generation_id)
            self._loop = asyncio.get_running_loop()
            if (
                self._gateway is not None
                and self._snapshot.desired_room_id == room_id
                and self._snapshot.state
                in {
                    LivestreamState.CONNECTING,
                    LivestreamState.PRELIVE,
                    LivestreamState.LIVE,
                    LivestreamState.RECONNECTING,
                }
            ):
                return self.snapshot()

            next_generation = self._snapshot.generation_id + 1
            await self._switch_scene_generation(room_id, next_generation)
            old_gateway = self._gateway
            self._gateway = None

            if old_gateway is not None:
                self._transition(
                    state=LivestreamState.STOPPING,
                    connected=False,
                    room_id=None,
                    desired_room_id=room_id,
                    generation_id=next_generation,
                    message="Switching rooms",
                )
                await self._publish_status()
                await self._cancel_callback_tasks()
                if self._reply_runtime is not None:
                    await self._reply_runtime.switch_generation(next_generation)
                stop_error = await self._stop_gateway(old_gateway)
                if stop_error is not None:
                    # Keep the uncertain transport as the owned gateway so a
                    # later command must retry stopping it before any new start.
                    self._gateway = old_gateway
                    self._transition(
                        state=LivestreamState.ERROR,
                        connected=False,
                        room_id=None,
                        desired_room_id=room_id,
                        error_code=stop_error,
                        message="Previous gateway did not stop",
                    )
                    await self._publish_status()
                    return self.snapshot()

            self._transition(
                state=LivestreamState.CONNECTING,
                connected=False,
                room_id=None,
                desired_room_id=room_id,
                retry_count=0,
                error_code=None,
                generation_id=next_generation,
                message="Connecting",
            )
            await self._cancel_callback_tasks()
            if self._reply_runtime is not None:
                await self._reply_runtime.switch_generation(next_generation)
            await self._publish_status()

            try:
                gateway = self._gateway_factory(room_id, sessdata)
                gateway.set_message_callback(
                    lambda message: self._schedule_message(next_generation, message),
                )
                set_event_callback = getattr(gateway, "set_event_callback", None)
                if callable(set_event_callback):
                    set_event_callback(
                        lambda event: self._schedule_event(next_generation, event),
                    )
                gateway.set_status_callback(
                    lambda connected, message: self._schedule_status(
                        next_generation,
                        connected,
                        message,
                    ),
                )
                self._gateway = gateway
                await asyncio.to_thread(gateway.start)
            except Exception as exc:
                logger.error(
                    "Failed to start Bilibili danmaku gateway: error_type={}",
                    type(exc).__name__,
                )
                self._gateway = None
                self._transition(
                    state=LivestreamState.ERROR,
                    connected=False,
                    room_id=None,
                    error_code="gateway_start_failed",
                    message="Bilibili gateway failed to start",
                )
                await self._publish_status()

            return self.snapshot()

    async def stop(
        self,
        *,
        expected_generation_id: int | None = None,
    ) -> dict[str, Any]:
        """Stop the owned gateway with a bounded, non-blocking wait."""
        async with self._lock:
            self._ensure_expected_generation(expected_generation_id)
            gateway = self._gateway
            if gateway is None and self._snapshot.state == LivestreamState.STOPPED:
                return self.snapshot()

            generation = self._snapshot.generation_id + 1
            scene_room_id = self._snapshot.room_id or self._snapshot.desired_room_id
            if scene_room_id is not None:
                await self._switch_scene_generation(scene_room_id, generation)
            self._gateway = None
            self._transition(
                state=LivestreamState.STOPPING,
                connected=False,
                room_id=None,
                desired_room_id=None,
                generation_id=generation,
                message="Stopping",
            )
            await self._publish_status()
            await self._cancel_callback_tasks()
            if self._reply_runtime is not None:
                await self._reply_runtime.switch_generation(generation)

            stop_error = await self._stop_gateway(gateway) if gateway else None
            if stop_error is not None and gateway is not None:
                # Preserve uncertain ownership. A later connect must retry the
                # stop and cannot create a second transport behind this one.
                self._gateway = gateway
            self._transition(
                state=LivestreamState.STOPPED,
                connected=False,
                room_id=None,
                desired_room_id=None,
                retry_count=0,
                error_code=stop_error,
                message=(
                    "Stopped with shutdown timeout"
                    if stop_error == "shutdown_timeout"
                    else "Stopped"
                ),
            )
            await self._publish_status()
            return self.snapshot()

    async def _switch_scene_generation(self, room_id: int, generation_id: int) -> None:
        """Reset optional scene state without making room lifecycle depend on it."""
        if self._scene_runtime is None:
            return
        try:
            await self._scene_runtime.switch_generation(
                room_id=room_id,
                generation_id=generation_id,
            )
        except Exception as exc:
            logger.warning(
                "Scene runtime generation reset failed: error_type={}",
                type(exc).__name__,
            )

    async def _stop_gateway(self, gateway: DanmakuGateway) -> str | None:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(gateway.stop),
                timeout=self._shutdown_timeout_seconds,
            )
        except TimeoutError:
            logger.warning("Bilibili gateway shutdown timed out")
            return "shutdown_timeout"
        except Exception:
            logger.error("Bilibili gateway shutdown failed")
            return "shutdown_failed"
        return None

    def _schedule_status(
        self,
        generation: int,
        connected: bool,
        message: str,
    ) -> None:
        self._schedule(
            lambda: self._handle_status(generation, connected, message),
        )

    def _schedule_message(self, generation: int, message: DanmakuMessage) -> None:
        self._schedule(lambda: self._handle_message(generation, message))

    def _schedule_event(self, generation: int, event: LivestreamEvent) -> None:
        self._schedule(lambda: self._handle_event(generation, event))

    def _schedule(self, coroutine_factory: Callable[[], Awaitable[None]]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def create_task() -> None:
            async def invoke_callback() -> None:
                await coroutine_factory()

            task: asyncio.Task[None] = asyncio.create_task(invoke_callback())
            self._callback_tasks.add(task)
            task.add_done_callback(self._callback_done)

        loop.call_soon_threadsafe(create_task)

    def _callback_done(self, task: asyncio.Task[None]) -> None:
        self._callback_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            logger.error(
                "Livestream callback failed: error_type={}",
                type(exception).__name__,
            )

    async def _cancel_callback_tasks(self) -> None:
        tasks = list(self._callback_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle_status(
        self,
        generation: int,
        connected: bool,
        message: str,
    ) -> None:
        async with self._lock:
            if generation != self._snapshot.generation_id or self._gateway is None:
                return

            if connected:
                self._transition(
                    state=LivestreamState.CONNECTING,
                    connected=True,
                    room_id=self._snapshot.desired_room_id,
                    retry_count=0,
                    error_code=None,
                    message="Checking broadcast state",
                )
            elif message in {
                "Dependency unavailable",
                "Invalid credentials",
                "Invalid room",
            }:
                error_code = {
                    "Dependency unavailable": "dependency_unavailable",
                    "Invalid credentials": "invalid_credentials",
                    "Invalid room": "invalid_room",
                }[message]
                self._transition(
                    state=LivestreamState.ERROR,
                    connected=False,
                    room_id=None,
                    error_code=error_code,
                    message=message,
                )
            elif message.startswith("Max retries reached"):
                self._transition(
                    state=LivestreamState.ERROR,
                    connected=False,
                    room_id=None,
                    retry_count=self._snapshot.retry_count + 1,
                    error_code="retry_exhausted",
                    message=message,
                )
            else:
                self._transition(
                    state=LivestreamState.RECONNECTING,
                    connected=False,
                    room_id=None,
                    retry_count=self._snapshot.retry_count + 1,
                    error_code=None,
                    message=message or "Reconnecting",
                )
            await self._publish_status()

    async def _handle_message(
        self,
        generation: int,
        message: DanmakuMessage,
    ) -> None:
        async with self._lock:
            if generation != self._snapshot.generation_id or self._gateway is None:
                return
            room_id = self._snapshot.desired_room_id

        if room_id is None:
            return
        self._metrics.received += 1
        if self._scene_runtime is not None:
            try:
                await self._scene_runtime.observe_danmaku(
                    message,
                    room_id=room_id,
                    generation_id=generation,
                )
            except Exception as exc:
                logger.warning(
                    "Scene runtime observation failed: error_type={}",
                    type(exc).__name__,
                )
        if self._buffer is not None:
            self._buffer.add(message.text, room_id=room_id)
        try:
            await self._raw_message_sink(message, room_id)
        except Exception as exc:
            logger.error(
                "Raw danmaku sink failed: error_type={}",
                type(exc).__name__,
            )
        else:
            self._metrics.displayed += 1
        if self._reply_runtime is not None:
            submission = await self._reply_runtime.submit(
                message,
                room_id=room_id,
                generation_id=generation,
            )
            try:
                await self._reply_decision_sink(message, submission, room_id)
            except Exception as exc:
                logger.error(
                    "Reply decision sink failed: error_type={}",
                    type(exc).__name__,
                )
        try:
            await self._candidate_sink(message, room_id, generation)
        except Exception as exc:
            logger.error(
                "Danmaku candidate sink failed: error_type={}",
                type(exc).__name__,
            )

    async def _handle_event(
        self,
        generation: int,
        event: LivestreamEvent,
    ) -> None:
        async with self._lock:
            if generation != self._snapshot.generation_id or self._gateway is None:
                return
            room_id = self._snapshot.desired_room_id
            status_changed = False
            if (
                event.event_type is LivestreamEventType.BROADCAST_STATE
                and self._snapshot.connected
                and isinstance(event.payload.get("live"), bool)
            ):
                next_state = (
                    LivestreamState.LIVE if event.payload["live"] else LivestreamState.PRELIVE
                )
                if self._snapshot.state is not next_state:
                    self._transition(
                        state=next_state,
                        message=str(event.payload.get("message") or next_state.value),
                    )
                    status_changed = True

        if room_id is None:
            return
        if status_changed:
            await self._publish_status()
        self._event_metrics.record_received(event)
        try:
            await self._raw_event_sink(event, room_id, generation)
        except Exception as exc:
            self._event_metrics.record_callback_failure()
            logger.error(
                "Raw livestream event sink failed: error_type={}",
                type(exc).__name__,
            )
        else:
            self._event_metrics.record_dispatched(event)

        message = event.to_danmaku_message(timestamp=self._clock())
        if message is not None:
            await self._handle_message(generation, message)

    def _transition(self, **changes: object) -> None:
        replace_snapshot = cast(Any, replace)
        self._snapshot = replace_snapshot(
            self._snapshot,
            **changes,
            updated_at=self._clock(),
        )

    def _ensure_expected_generation(self, expected_generation_id: int | None) -> None:
        if (
            expected_generation_id is not None
            and expected_generation_id != self._snapshot.generation_id
        ):
            raise StaleGenerationError("livestream generation changed")

    async def _publish_status(self) -> None:
        try:
            await self._status_sink(self.snapshot())
        except Exception:
            logger.exception("Livestream status sink failed")
