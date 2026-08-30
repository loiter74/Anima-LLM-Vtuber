"""Fact-only Minecraft activity narration for public livestream surfaces."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal

from loguru import logger

PresentationMode = Literal["off", "visual_only", "full"]
NarrationEmitter = Callable[[str, dict[str, Any], str | None], Awaitable[None]]
NarrationStarted = Callable[[], Awaitable[None]]
NarrationSpeaker = Callable[["NarrationCue", NarrationStarted], Awaitable[str | None]]
NarrationInterrupt = Callable[["NarrationCue"], Awaitable[None]]
BusyProbe = Callable[[], bool]

_PHASES = frozenset(
    {"planning", "observing", "committed", "acting", "checking", "recovering", "finished"}
)
_OUTCOMES = frozenset({"active", "succeeded", "failed", "cancelled", "blocked"})
_INTENT_TEXT = {
    "acquire": "收集",
    "craft": "制作",
    "build": "搭建",
    "travel": "前往",
    "combat": "应对",
    "survive": "确保安全",
    "learn": "试着掌握",
    "discover": "探索",
    "interact": "处理",
}
_INTENTS = frozenset(_INTENT_TEXT)
_FOCUS_KINDS = frozenset({"item", "entity", "place", "structure", "condition"})
_PROGRESS_UNITS = frozenset({"objectives", "items", "blocks", "actions"})
_PHASE_EMOTION = {
    "planning": "thinking",
    "observing": "thinking",
    "committed": "confident",
    "acting": "focused",
    "checking": "thinking",
    "recovering": "alert",
    "finished": "relieved",
}


@dataclass(frozen=True, slots=True)
class NarrationCue:
    cue_id: str
    source_event_id: str
    phase: str
    visual_text: str
    emotion: str
    priority: int
    expires_at: float


class BroadcastNarrationDirector:
    """Project verified activity into visual state and sparse host narration."""

    def __init__(
        self,
        emit: NarrationEmitter,
        *,
        speaker: NarrationSpeaker | None = None,
        mode: PresentationMode = "off",
        replay_limit: int = 64,
        busy: BusyProbe | None = None,
        singing: BusyProbe | None = None,
        interrupt: NarrationInterrupt | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(replay_limit, bool) or not 1 <= replay_limit <= 256:
            raise ValueError("invalid narration replay limit")
        self._emit = emit
        self._speaker = speaker
        self._mode = mode
        self._replay_limit = replay_limit
        self._recent: deque[tuple[dict[str, Any], dict[str, Any]]] = deque(maxlen=replay_limit)
        self._seen: deque[str] = deque(maxlen=max(128, replay_limit * 4))
        self._seen_set: set[str] = set()
        self._busy = busy or (lambda: False)
        self._singing = singing or (lambda: False)
        self._interrupt = interrupt
        self._clock = clock
        self._last_spoken_at = float("-inf")
        self._tasks: set[asyncio.Task[None]] = set()
        self._pending_progress: dict[str, asyncio.Task[None]] = {}
        self._superseded_cues: set[str] = set()
        self._started_cues: set[str] = set()
        self._submission_lock = asyncio.Lock()
        self._highest_sequence = 0
        self._generation = 0

    @property
    def mode(self) -> PresentationMode:
        return self._mode

    @property
    def replay_limit(self) -> int:
        return self._replay_limit

    def configure(
        self,
        mode: PresentationMode,
        *,
        replay_limit: int | None = None,
    ) -> None:
        if mode not in {"off", "visual_only", "full"}:
            raise ValueError("invalid presentation mode")
        if replay_limit is not None:
            if isinstance(replay_limit, bool) or not 1 <= replay_limit <= 256:
                raise ValueError("invalid narration replay limit")
            if replay_limit != self._replay_limit:
                self._resize_replay(replay_limit)
        changed = mode != self._mode
        self._mode = mode
        if changed and mode != "full":
            self._generation += 1
            self._cancel_pending()

    async def switch_generation(self) -> None:
        self._generation += 1
        tasks = tuple(self._tasks)
        self._cancel_pending()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def submit(self, projection: Mapping[str, Any]) -> None:
        if self._mode == "off":
            return
        detached = _validate_projection(projection)
        event_id = str(detached["event_id"])
        sequence = _activity_sequence(detached)
        async with self._submission_lock:
            if event_id in self._seen_set or sequence <= self._highest_sequence:
                return
            state = _narration_state(detached, speech_state="none")
            await self._emit("minecraft:activity_projection", detached, None)
            await self._emit("livestream:narration_state", state, None)
            self._remember(event_id)
            self._highest_sequence = sequence
            self._recent.append((detached, state))

        if self._mode != "full" or self._speaker is None:
            return
        cue = _cue(detached, state, now=self._clock())
        generation = self._generation
        progress_key = _progress_key(detached) if cue.priority == 50 else None
        if progress_key is not None:
            previous = self._pending_progress.get(progress_key)
            if previous is not None and not previous.done():
                previous_cue_id = previous.get_name().removeprefix("minecraft-narration-")
                if previous_cue_id not in self._started_cues:
                    self._superseded_cues.add(previous_cue_id)
                    previous.cancel()
        task = asyncio.create_task(
            self._deliver(cue, state, generation),
            name=f"minecraft-narration-{cue.cue_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        if progress_key is not None:
            self._pending_progress[progress_key] = task
            task.add_done_callback(partial(self._forget_pending, progress_key))

    async def replay(self, sid: str) -> None:
        if self._mode == "off":
            return
        for activity, state in tuple(self._recent):
            await self._emit("minecraft:activity_projection", dict(activity), sid)
            await self._emit("livestream:narration_state", dict(state), sid)

    async def replay_persisted(
        self,
        projections: list[Mapping[str, Any]],
        sid: str,
    ) -> None:
        """Replay journal facts to one public client without generating speech."""

        if self._mode == "off":
            return
        validated: list[dict[str, Any]] = []
        for projection in projections:
            try:
                validated.append(_validate_projection(projection))
            except Exception as exc:
                logger.warning(
                    "Minecraft public activity replay skipped: error_type={}",
                    type(exc).__name__,
                )
        replayed: set[str] = set()
        async with self._submission_lock:
            for detached in sorted(validated, key=_activity_sequence):
                event_id = str(detached["event_id"])
                if event_id in replayed:
                    continue
                replayed.add(event_id)
                state = _narration_state(detached, speech_state="none")
                await self._emit("minecraft:activity_projection", detached, sid)
                await self._emit("livestream:narration_state", state, sid)
                self._highest_sequence = max(
                    self._highest_sequence,
                    _activity_sequence(detached),
                )
                if all(item[0]["event_id"] != event_id for item in self._recent):
                    self._recent.append((detached, state))

    async def close(self) -> None:
        await self.switch_generation()

    async def _deliver(
        self,
        cue: NarrationCue,
        state: dict[str, Any],
        generation: int,
    ) -> None:
        terminal = cue.phase in {"recovering", "finished"}
        try:
            while generation == self._generation:
                now = self._clock()
                if now >= cue.expires_at:
                    return
                cooled_down = terminal or now - self._last_spoken_at >= 6.0
                if cooled_down and not self._busy() and not self._singing():
                    break
                await asyncio.sleep(min(0.1, max(0.01, cue.expires_at - now)))
            if generation != self._generation:
                return
            queued = {**state, "speech_state": "queued", "task_id": cue.cue_id}
            await self._emit("livestream:narration_state", queued, None)

            async def on_started() -> None:
                if generation != self._generation:
                    raise asyncio.CancelledError
                self._started_cues.add(cue.cue_id)
                speaking = {**queued, "speech_state": "speaking"}
                await self._emit("livestream:narration_state", speaking, None)

            spoken = await self._speaker(cue, on_started)
            if not spoken:
                cancelled = {**queued, "speech_state": "cancelled"}
                await self._emit("livestream:narration_state", cancelled, None)
                return
            self._last_spoken_at = self._clock()
            completed = {**queued, "speech_state": "completed"}
            await self._emit("livestream:narration_state", completed, None)
        except asyncio.CancelledError:
            if cue.cue_id in self._superseded_cues:
                self._superseded_cues.discard(cue.cue_id)
                return
            if cue.cue_id in self._started_cues and self._interrupt is not None:
                try:
                    await self._interrupt(cue)
                except Exception as exc:
                    logger.warning(
                        "Minecraft narration interruption failed: error_type={}",
                        type(exc).__name__,
                    )
            cancelled = {**state, "speech_state": "cancelled", "task_id": cue.cue_id}
            await self._emit("livestream:narration_state", cancelled, None)
            raise
        except Exception as exc:
            cancelled = {**state, "speech_state": "cancelled", "task_id": cue.cue_id}
            await self._emit("livestream:narration_state", cancelled, None)
            logger.warning(
                "Minecraft narration skipped: phase={} error_type={}",
                cue.phase,
                type(exc).__name__,
            )
        finally:
            self._started_cues.discard(cue.cue_id)

    def _cancel_pending(self) -> None:
        self._pending_progress.clear()
        for task in tuple(self._tasks):
            if not task.done():
                task.cancel()

    def _remember(self, event_id: str) -> None:
        if len(self._seen) == self._seen.maxlen:
            removed = self._seen.popleft()
            self._seen_set.discard(removed)
        self._seen.append(event_id)
        self._seen_set.add(event_id)

    def _forget_pending(self, key: str, task: asyncio.Task[None]) -> None:
        if self._pending_progress.get(key) is task:
            self._pending_progress.pop(key, None)

    def _resize_replay(self, replay_limit: int) -> None:
        self._replay_limit = replay_limit
        self._recent = deque(tuple(self._recent)[-replay_limit:], maxlen=replay_limit)
        seen_limit = max(128, replay_limit * 4)
        self._seen = deque(tuple(self._seen)[-seen_limit:], maxlen=seen_limit)
        self._seen_set = set(self._seen)


def _validate_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "event",
        "event_id",
        "projection_kind",
        "projection_version",
        "occurred_at_ms",
        "mission_id",
        "entity_id",
        "payload",
    }
    if set(value) - allowed:
        raise ValueError("public activity contains unknown fields")
    if (
        value.get("schema_version") != "1"
        or value.get("event") != "minecraft.activity.projection"
        or value.get("projection_kind") != "activity"
        or value.get("entity_id") != "minecraft"
    ):
        raise ValueError("public activity envelope is invalid")
    event_id = value.get("event_id")
    version = value.get("projection_version")
    occurred_at_ms = value.get("occurred_at_ms")
    mission_id = value.get("mission_id")
    payload = value.get("payload")
    if not isinstance(event_id, str) or not event_id.startswith("activity:"):
        raise ValueError("public activity event_id is invalid")
    if not isinstance(payload, Mapping):
        raise ValueError("public activity payload is invalid")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("public activity projection version is invalid")
    try:
        sequence = int(event_id.removeprefix("activity:"))
    except ValueError as exc:
        raise ValueError("public activity event_id is invalid") from exc
    if sequence < 1 or event_id != f"activity:{sequence}" or version != sequence:
        raise ValueError("public activity sequence is invalid")
    if (
        isinstance(occurred_at_ms, bool)
        or not isinstance(occurred_at_ms, int)
        or occurred_at_ms < 0
    ):
        raise ValueError("public activity timestamp is invalid")
    if mission_id is not None and (
        not isinstance(mission_id, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", mission_id) is None
    ):
        raise ValueError("public activity mission is invalid")
    allowed_payload = {"phase", "intent", "focus", "progress", "outcome"}
    if set(payload) - allowed_payload:
        raise ValueError("public activity payload contains private fields")
    phase = payload.get("phase")
    outcome = payload.get("outcome", "active")
    if phase not in _PHASES or outcome not in _OUTCOMES:
        raise ValueError("public activity state is invalid")
    intent = payload.get("intent")
    if intent is not None and intent not in _INTENTS:
        raise ValueError("public activity intent is invalid")
    if (outcome != "active") != (phase == "finished"):
        raise ValueError("public activity phase and terminal outcome are inconsistent")
    focus = payload.get("focus")
    if focus is not None:
        if not isinstance(focus, Mapping) or set(focus) != {"kind", "label"}:
            raise ValueError("public activity focus is invalid")
        label = focus.get("label")
        if focus.get("kind") not in _FOCUS_KINDS:
            raise ValueError("public activity focus kind is invalid")
        if not isinstance(label, str) or not label or len(label) > 64:
            raise ValueError("public activity focus label is invalid")
    progress = payload.get("progress")
    if progress is not None:
        if not isinstance(progress, Mapping) or set(progress) != {
            "current",
            "total",
            "unit",
        }:
            raise ValueError("public activity progress is invalid")
        current = progress.get("current")
        total = progress.get("total")
        if (
            isinstance(current, bool)
            or isinstance(total, bool)
            or not isinstance(current, int)
            or not isinstance(total, int)
            or current < 0
            or total < 1
            or current > total
            or progress.get("unit") not in _PROGRESS_UNITS
        ):
            raise ValueError("public activity progress is invalid")
    return {key: _detach(item) for key, item in value.items()}


def _activity_sequence(projection: Mapping[str, Any]) -> int:
    return int(str(projection["event_id"]).removeprefix("activity:"))


def _detach(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _detach(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_detach(item) for item in value]
    return value


def _narration_state(projection: Mapping[str, Any], *, speech_state: str) -> dict[str, Any]:
    payload = projection["payload"]
    assert isinstance(payload, Mapping)
    phase = str(payload["phase"])
    cue_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(projection["event_id"])))
    return {
        "schema_version": "1",
        "cue_id": cue_id,
        "source_event_id": str(projection["event_id"]),
        "phase": phase,
        "visual_text": _visual_text(payload)[:80],
        "emotion": _PHASE_EMOTION[phase],
        "speech_state": speech_state,
        "occurred_at_ms": int(projection["occurred_at_ms"]),
    }


def _cue(
    projection: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    now: float,
) -> NarrationCue:
    phase = str(state["phase"])
    outcome = str(projection["payload"].get("outcome", "active"))
    priority = (
        30
        if phase == "recovering" or outcome in {"failed", "blocked"}
        else 40
        if phase == "finished"
        else 50
    )
    ttl = 60.0 if priority <= 40 else 15.0
    return NarrationCue(
        cue_id=str(state["cue_id"]),
        source_event_id=str(state["source_event_id"]),
        phase=phase,
        visual_text=str(state["visual_text"]),
        emotion=str(state["emotion"]),
        priority=priority,
        expires_at=now + ttl,
    )


def _progress_key(projection: Mapping[str, Any]) -> str:
    mission_id = projection.get("mission_id")
    if isinstance(mission_id, str) and mission_id:
        return f"mission:{mission_id}"
    return "mission:unscoped"


def _visual_text(payload: Mapping[str, Any]) -> str:
    phase = str(payload["phase"])
    outcome = str(payload.get("outcome", "active"))
    intent = _INTENT_TEXT.get(str(payload.get("intent") or ""), "处理")
    focus = payload.get("focus")
    label = str(focus.get("label")) if isinstance(focus, Mapping) else "当前目标"
    if phase == "planning":
        return f"我先想清楚怎么{intent}{label}。"
    if phase == "observing":
        return f"先看看{label}周围的情况。"
    if phase == "committed":
        return f"目标确定，开始{intent}{label}。"
    if phase == "acting":
        return f"正在{intent}{label}。"
    if phase == "checking":
        return f"等一下，我确认{label}是否真的完成。"
    if phase == "recovering":
        return f"刚才没有按预期进行，我正在调整{label}。"
    terminal = {
        "succeeded": f"{label}已经确认完成。",
        "failed": f"{label}这次没有完成。",
        "cancelled": f"{label}已经停止。",
        "blocked": f"{label}暂时被卡住了。",
    }
    return terminal.get(outcome, f"{label}已经结束。")
