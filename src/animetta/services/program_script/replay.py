"""Creator-controlled replay coordinator built on ReplayDanmakuGateway."""

from __future__ import annotations

import asyncio
import json
import math
import threading
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from animetta.checkpointing import CheckpointRequest
from animetta.services.bilibili.models import LivestreamEvent, LivestreamEventType
from animetta.services.bilibili.replay_gateway import ReplayDanmakuGateway

from .models import InputType, MemoryMode, ProgramScript, ThreadMode

ReplayDispatcher = Callable[[LivestreamEvent], Coroutine[Any, Any, None]]
RoomStateProvider = Callable[[int], dict[str, Any]]
CheckpointDelete = Callable[[str], Awaitable[None]]


class ReplayCoordinatorError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ReplayState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True)
class ReplayRun:
    replay_id: str
    room_id: int
    creator_id: str
    source: str
    events: tuple[LivestreamEvent, ...]
    speed: float
    actor_id: str
    state: ReplayState = ReplayState.IDLE
    cursor: int = 0
    error: str | None = None
    gateway: ReplayDanmakuGateway | None = None
    step_mode: bool = False
    stopping_for_control: bool = False
    control_target: ReplayState | None = None
    checkpoint_threads: set[str] = field(default_factory=set)


class ProgramReplayCoordinator:
    """Pause and re-slice immutable event sources without duplicating gateway scheduling."""

    def __init__(
        self,
        *,
        control_timeout_seconds: float = 50.0,
        checkpoint_delete: CheckpointDelete | None = None,
    ) -> None:
        if not math.isfinite(control_timeout_seconds) or control_timeout_seconds <= 0:
            raise ValueError("control_timeout_seconds must be positive")
        self._dispatcher: ReplayDispatcher | None = None
        self._room_state_provider: RoomStateProvider | None = None
        self._runs: dict[str, ReplayRun] = {}
        self._active_by_room: dict[int, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._control_timeout_seconds = control_timeout_seconds
        self._checkpoint_delete = checkpoint_delete

    def set_dispatcher(self, dispatcher: ReplayDispatcher) -> None:
        self._dispatcher = dispatcher

    def set_room_state_provider(self, provider: RoomStateProvider) -> None:
        self._room_state_provider = provider

    async def start(
        self,
        events: Sequence[LivestreamEvent],
        *,
        room_id: int,
        creator_id: str,
        source: str,
        speed: float,
    ) -> dict[str, Any]:
        if self._dispatcher is None:
            raise ReplayCoordinatorError(
                "runtime_not_ready", "弹幕重放链路尚未就绪", status_code=503
            )
        if not math.isfinite(speed) or speed <= 0 or speed > 100:
            raise ReplayCoordinatorError("invalid_speed", "重放速度必须在 0 到 100 之间")
        active = self._active_run(room_id)
        if active is not None:
            raise ReplayCoordinatorError(
                "replay_already_active", "该房间已有重放任务", status_code=409
            )
        if not events:
            raise ReplayCoordinatorError("empty_replay", "重放事件不能为空")
        self._ensure_room_available(room_id)
        self._loop = asyncio.get_running_loop()
        replay_id = str(uuid4())
        run = ReplayRun(
            replay_id=replay_id,
            room_id=room_id,
            creator_id=creator_id,
            source=source,
            events=tuple(events),
            speed=speed,
            actor_id=f"replay:{replay_id}",
        )
        self._runs[replay_id] = run
        self._active_by_room[room_id] = replay_id
        self._start_gateway(run)
        return self.snapshot(run)

    async def control(
        self,
        replay_id: str,
        action: str,
        *,
        creator_id: str,
        speed: float | None = None,
    ) -> dict[str, Any]:
        run = self._owned_run(replay_id, creator_id)
        if action == "pause":
            await self._pause(run)
        elif action == "resume":
            if run.state is not ReplayState.PAUSED:
                raise ReplayCoordinatorError("not_paused", "重放当前未暂停", status_code=409)
            self._start_gateway(run)
        elif action == "step":
            if run.state not in {ReplayState.PAUSED, ReplayState.IDLE}:
                raise ReplayCoordinatorError(
                    "step_requires_pause", "单步前请先暂停", status_code=409
                )
            if run.cursor < len(run.events):
                run.step_mode = True
                self._start_gateway(run, limit=1)
        elif action == "speed":
            if speed is None or not math.isfinite(speed) or speed <= 0 or speed > 100:
                raise ReplayCoordinatorError("invalid_speed", "重放速度必须在 0 到 100 之间")
            was_running = run.state is ReplayState.RUNNING
            if was_running:
                await self._pause(run)
            run.speed = speed
            if was_running:
                self._start_gateway(run)
        elif action == "restart":
            events = run.events
            room_id = run.room_id
            source = run.source
            current_speed = run.speed if speed is None else speed
            await self._stop(run)
            return await self.start(
                events,
                room_id=room_id,
                creator_id=creator_id,
                source=source,
                speed=current_speed,
            )
        elif action == "stop":
            await self._stop(run)
        else:
            raise ReplayCoordinatorError("invalid_control", "未知重放控制命令")
        return self.snapshot(run)

    def get_run(self, replay_id: str) -> dict[str, Any]:
        run = self._runs.get(replay_id)
        if run is None:
            raise ReplayCoordinatorError("replay_not_found", "重放任务不存在", status_code=404)
        return self.snapshot(run)

    async def shutdown(self) -> None:
        for run in tuple(self._runs.values()):
            if run.state in {ReplayState.RUNNING, ReplayState.PAUSED}:
                await self._stop(run)

    def is_active(self, room_id: int) -> bool:
        return self._active_run(room_id) is not None

    def snapshot(self, run: ReplayRun) -> dict[str, Any]:
        current = run.events[run.cursor] if run.cursor < len(run.events) else None
        return {
            "replay_id": run.replay_id,
            "room_id": run.room_id,
            "source": run.source,
            "state": run.state,
            "speed": run.speed,
            "cursor": run.cursor,
            "total_events": len(run.events),
            "error": run.error,
            "current_event": current.to_dict() if current else None,
        }

    def _start_gateway(self, run: ReplayRun, *, limit: int | None = None) -> None:
        remaining = run.events[run.cursor :]
        if limit is not None:
            remaining = remaining[:limit]
        if not remaining:
            run.state = ReplayState.COMPLETED
            self._active_by_room.pop(run.room_id, None)
            self._schedule_checkpoint_cleanup(run)
            return
        rebased = _rebase_events(remaining)
        gateway = ReplayDanmakuGateway(
            rebased,
            speed=run.speed,
            shutdown_timeout_seconds=self._control_timeout_seconds,
        )
        gateway.set_event_callback(lambda event: self._dispatch_from_worker(run, event))
        gateway.set_status_callback(
            lambda connected, message: self._status_from_worker(run, connected, message)
        )
        run.gateway = gateway
        run.stopping_for_control = False
        run.state = ReplayState.RUNNING
        gateway.start()

    def _dispatch_from_worker(self, run: ReplayRun, rebased: LivestreamEvent) -> None:
        if self._loop is None or self._dispatcher is None:
            return
        future: Future[None] = asyncio.run_coroutine_threadsafe(
            self._dispatch_if_room_available(run),
            self._loop,
        )
        try:
            future.result()
        except ReplayCoordinatorError as exc:
            gateway = run.gateway
            if gateway is not None:
                gateway.stop()
            self._loop.call_soon_threadsafe(self._mark_failed, run, exc.code)
            raise
        except Exception as exc:
            gateway = run.gateway
            if gateway is not None:
                gateway.stop()
            self._loop.call_soon_threadsafe(
                self._mark_failed,
                run,
                type(exc).__name__,
            )
            raise

    async def _dispatch_if_room_available(
        self,
        run: ReplayRun,
    ) -> None:
        if self._dispatcher is None:
            return
        self._ensure_room_available(run.room_id)
        original = run.events[run.cursor]
        payload = dict(original.payload)
        context = dict(payload.get("program_context", {}))
        checkpoint_thread = (
            f"replay:{run.replay_id}:{run.cursor}"
            if context.get("isolated")
            else f"replay:{run.replay_id}"
        )
        run.checkpoint_threads.add(checkpoint_thread)
        context.update(
            {
                "actor_id": run.actor_id,
                "turn_id": str(uuid4()),
                "program_run_id": run.replay_id,
                "room_id": run.room_id,
                "checkpoint_request": CheckpointRequest(
                    thread_id=checkpoint_thread,
                    owner_kind="replay",
                    owner_id=run.replay_id,
                    retention="stable",
                ),
            }
        )
        payload["program_context"] = context
        dispatched = LivestreamEvent(
            sequence=original.sequence,
            offset_ms=original.offset_ms,
            event_type=original.event_type,
            actor_id=original.actor_id,
            text=original.text,
            payload=payload,
        )
        await self._dispatcher(dispatched)
        with self._lock:
            run.cursor += 1

    def _status_from_worker(self, run: ReplayRun, connected: bool, message: str) -> None:
        if connected or self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._finish_gateway, run, message)

    def _finish_gateway(self, run: ReplayRun, message: str) -> None:
        run.gateway = None
        if run.state is ReplayState.FAILED:
            return
        if run.stopping_for_control:
            target = run.control_target
            if target is not None:
                self._complete_control(run, target)
            return
        if run.step_mode:
            run.step_mode = False
            run.state = ReplayState.PAUSED
        elif run.cursor >= len(run.events):
            run.state = ReplayState.COMPLETED
            self._active_by_room.pop(run.room_id, None)
            self._schedule_checkpoint_cleanup(run)
        elif message == "Replay stopped":
            run.state = ReplayState.PAUSED

    def _mark_failed(self, run: ReplayRun, reason: str) -> None:
        run.state = ReplayState.FAILED
        run.error = reason
        self._active_by_room.pop(run.room_id, None)
        self._schedule_checkpoint_cleanup(run)

    async def _pause(self, run: ReplayRun) -> None:
        if run.state is not ReplayState.RUNNING:
            return
        await self._stop_gateway_for_control(
            run,
            ReplayState.PAUSED,
            "当前事件仍在处理，暂停将在本轮完成后生效",
        )
        self._complete_control(run, ReplayState.PAUSED)

    async def _stop(self, run: ReplayRun) -> None:
        await self._stop_gateway_for_control(
            run,
            ReplayState.STOPPED,
            "当前事件仍在处理，停止将在本轮完成后生效",
        )
        self._complete_control(run, ReplayState.STOPPED)
        await self._delete_checkpoints(run)

    async def _stop_gateway_for_control(
        self,
        run: ReplayRun,
        target: ReplayState,
        timeout_message: str,
    ) -> None:
        run.stopping_for_control = True
        run.control_target = target
        gateway = run.gateway
        if gateway is None:
            return
        try:
            await asyncio.to_thread(gateway.stop)
        except TimeoutError as exc:
            raise ReplayCoordinatorError(
                "replay_control_timeout",
                timeout_message,
                status_code=504,
            ) from exc

    def _complete_control(self, run: ReplayRun, target: ReplayState) -> None:
        run.gateway = None
        run.stopping_for_control = False
        run.control_target = None
        run.state = target
        if target is ReplayState.STOPPED:
            self._active_by_room.pop(run.room_id, None)

    def _schedule_checkpoint_cleanup(self, run: ReplayRun) -> None:
        if self._loop is not None:
            self._loop.create_task(self._delete_checkpoints(run))

    async def _delete_checkpoints(self, run: ReplayRun) -> None:
        if self._checkpoint_delete is None:
            return
        for thread_id in sorted(run.checkpoint_threads):
            await self._checkpoint_delete(thread_id)
        run.checkpoint_threads.clear()

    def _active_run(self, room_id: int) -> ReplayRun | None:
        replay_id = self._active_by_room.get(room_id)
        run = self._runs.get(replay_id or "")
        if run is None or run.state not in {ReplayState.RUNNING, ReplayState.PAUSED}:
            self._active_by_room.pop(room_id, None)
            return None
        return run

    def _ensure_room_available(self, room_id: int) -> None:
        if self._room_state_provider is None:
            return
        snapshot = self._room_state_provider(room_id)
        state = str(snapshot.get("state", "idle"))
        connected_room = snapshot.get("room_id") or snapshot.get("desired_room_id")
        if state in {"idle", "stopped"} or (state == "prelive" and connected_room == room_id):
            return
        raise ReplayCoordinatorError(
            "room_input_active",
            "真实直播、其他房间连接或节目运行活动时不能启动重放",
            status_code=409,
        )

    def _owned_run(self, replay_id: str, creator_id: str) -> ReplayRun:
        run = self._runs.get(replay_id)
        if run is None:
            raise ReplayCoordinatorError("replay_not_found", "重放任务不存在", status_code=404)
        if run.creator_id != creator_id:
            raise ReplayCoordinatorError(
                "creator_mismatch", "只有启动重放的 Creator 可以控制", status_code=403
            )
        return run


def compile_script_events(
    script: ProgramScript,
    selections: dict[str, str] | None = None,
) -> list[LivestreamEvent]:
    """Compile one deterministic test-viewer trace from a script and slot selections."""
    chosen = selections or {}
    slots: dict[str, str] = {}
    events: list[LivestreamEvent] = []
    for index, beat in enumerate(script.beats):
        if beat.input.type is InputType.FIXED:
            text = str(beat.input.text)
        else:
            options = list(script.option_sets[str(beat.input.options)])
            if beat.input.exclude_slot:
                options = [
                    option for option in options if option.id != slots.get(beat.input.exclude_slot)
                ]
            selected_id = chosen.get(str(beat.input.save_as))
            option = next((item for item in options if item.id == selected_id), options[0])
            text = option.danmaku
            slots[str(beat.input.save_as)] = option.id
        context = {
            "display_name": "首播测试观众",
            "program_beat_id": beat.id,
            "is_probe": beat.memory is MemoryMode.PROBE,
            "isolated": beat.thread is ThreadMode.ISOLATED,
            "memory_mode": beat.memory.value,
            "reply": beat.reply.model_dump(mode="json"),
        }
        events.append(
            LivestreamEvent(
                sequence=index,
                offset_ms=index * 1_000,
                event_type=LivestreamEventType.DANMAKU,
                actor_id="首播测试观众",
                text=text,
                payload={"user_id": 0, "program_context": context},
            )
        )
    return events


def parse_jsonl_events(content: str) -> list[LivestreamEvent]:
    events: list[LivestreamEvent] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            event = LivestreamEvent(
                sequence=len(events),
                offset_ms=int(data["offset_ms"]),
                event_type=LivestreamEventType(str(data["event_type"])),
                actor_id=str(data.get("actor_id", "首播测试观众")),
                text=str(data.get("text", "")),
                payload=dict(data.get("payload", {})),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReplayCoordinatorError(
                "invalid_jsonl", f"JSONL 第 {line_number} 行无效：{exc}"
            ) from exc
        events.append(event)
    return events


def _rebase_events(events: Sequence[LivestreamEvent]) -> list[LivestreamEvent]:
    base_offset = events[0].offset_ms
    return [
        LivestreamEvent(
            sequence=index,
            offset_ms=max(0, event.offset_ms - base_offset),
            event_type=event.event_type,
            actor_id=event.actor_id,
            text=event.text,
            payload=event.payload,
        )
        for index, event in enumerate(events)
    ]
