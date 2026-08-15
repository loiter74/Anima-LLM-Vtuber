"""Thin linear runner for published program scripts."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from animetta.orchestration.graph.checkpointing import CheckpointRequest

from .models import (
    EvaluatorType,
    InputType,
    MemoryMode,
    ProgramBeat,
    ProgramScript,
    ScriptOption,
    ThreadMode,
)
from .repository import ProgramScriptRepository

ProgramDispatcher = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
RoomStateProvider = Callable[[int], dict[str, Any]]
CheckpointDelete = Callable[[str], Awaitable[None]]


class ProgramRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class RunState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class ProbeResult(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    INCONCLUSIVE = "inconclusive"


@dataclass(slots=True)
class TurnRecord:
    beat_id: str
    input_text: str
    response_text: str
    turn_id: str
    memory_revision: int | None = None
    atom_id: str | None = None
    probe_result: ProbeResult | None = None
    degradation_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "input_text": self.input_text,
            "response_text": self.response_text,
            "turn_id": self.turn_id,
            "memory_revision": self.memory_revision,
            "atom_id": self.atom_id,
            "probe_result": self.probe_result,
            "degradation_reason": self.degradation_reason,
        }


@dataclass(slots=True)
class ProgramRun:
    run_id: str
    room_id: int
    creator_id: str
    actor_id: str
    script_version: int
    script_hash: str
    script: ProgramScript
    state: RunState = RunState.RUNNING
    current_index: int = 0
    waiting_for: str = "choice"
    slots: dict[str, str] = field(default_factory=dict)
    records: list[TurnRecord] = field(default_factory=list)
    atom_ids: list[str] = field(default_factory=list)
    error: str | None = None
    last_input: str | None = None
    last_option_id: str | None = None
    checkpoint_threads: set[str] = field(default_factory=set)


class ProgramScriptRunner:
    """Advance one immutable script snapshot without scene classification."""

    def __init__(
        self,
        repository: ProgramScriptRepository,
        *,
        memory_runtime: Any = None,
        checkpoint_delete: CheckpointDelete | None = None,
    ) -> None:
        self.repository = repository
        self.memory_runtime = memory_runtime
        self._dispatcher: ProgramDispatcher | None = None
        self._room_state_provider: RoomStateProvider | None = None
        self._runs: dict[str, ProgramRun] = {}
        self._active_by_room: dict[int, str] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._memory_receipts: dict[str, asyncio.Future[dict[str, object]]] = {}
        self._unsubscribe_revision: Callable[[], None] | None = None
        self._checkpoint_delete = checkpoint_delete
        if memory_runtime is not None:
            self._unsubscribe_revision = memory_runtime.subscribe_revision(self._on_memory_revision)

    def set_dispatcher(self, dispatcher: ProgramDispatcher) -> None:
        self._dispatcher = dispatcher

    def set_room_state_provider(self, provider: RoomStateProvider) -> None:
        self._room_state_provider = provider

    async def start(
        self,
        script_id: str,
        version: int,
        *,
        room_id: int,
        creator_id: str,
    ) -> dict[str, Any]:
        active = self._active_run(room_id)
        if active is not None:
            raise ProgramRuntimeError(
                "run_already_active", "该房间已有节目正在运行", status_code=409
            )
        if self._dispatcher is None:
            raise ProgramRuntimeError("runtime_not_ready", "节目运行链路尚未就绪", status_code=503)
        if self._room_state_provider is not None:
            room_state = str(self._room_state_provider(room_id).get("state", "idle"))
            if room_state not in {"idle", "stopped"}:
                raise ProgramRuntimeError(
                    "live_room_active", "真实直播弹幕连接活动时不能启动节目测试", status_code=409
                )

        published = self.repository.get_published(script_id, version)
        if not published.builtin and self.repository.is_archived(script_id):
            raise ProgramRuntimeError(
                "script_archived", "已归档脚本不能启动新节目", status_code=409
            )
        run_id = str(uuid4())
        run = ProgramRun(
            run_id=run_id,
            room_id=room_id,
            creator_id=creator_id,
            actor_id=f"program:{run_id}",
            script_version=published.version,
            script_hash=published.content_hash,
            script=published.script.model_copy(deep=True),
        )
        self._runs[run_id] = run
        self._active_by_room[room_id] = run_id
        self._prepare_current(run)
        return self.snapshot(run)

    async def submit_choice(
        self,
        run_id: str,
        beat_id: str,
        option_id: str,
        *,
        creator_id: str,
    ) -> dict[str, Any]:
        run = self._owned_run(run_id, creator_id)
        self._ensure_runnable(run)
        beat = self._current_beat(run)
        if beat.id != beat_id:
            raise ProgramRuntimeError("stale_beat", "题目已经变化", status_code=409)
        if beat.input.type is not InputType.CHOICE:
            raise ProgramRuntimeError("choice_not_expected", "当前轮不接受选项")
        option = self._available_option(run, beat, option_id)
        run.last_input = option.danmaku
        run.last_option_id = option.id
        run.waiting_for = "reply"
        self._schedule(run, option.danmaku, option)
        return self.snapshot(run)

    async def control(
        self,
        run_id: str,
        action: str,
        *,
        creator_id: str,
    ) -> dict[str, Any]:
        run = self._owned_run(run_id, creator_id)
        if action == "pause":
            if run.state is RunState.RUNNING:
                run.state = RunState.PAUSED
        elif action == "resume":
            if run.state is not RunState.PAUSED:
                raise ProgramRuntimeError("not_paused", "节目当前未暂停", status_code=409)
            run.state = RunState.RUNNING
            if run.run_id not in self._tasks:
                self._prepare_current(run)
        elif action == "retry":
            await self._retry(run)
        elif action == "stop":
            await self._stop(run)
        else:
            raise ProgramRuntimeError("invalid_control", "未知节目控制命令")
        return self.snapshot(run)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise ProgramRuntimeError("run_not_found", "节目运行不存在", status_code=404)
        return self.snapshot(run)

    def get_current(self, room_id: int) -> dict[str, Any] | None:
        run = self._active_run(room_id)
        return self.snapshot(run) if run is not None else None

    def is_active(self, room_id: int) -> bool:
        return self._active_run(room_id) is not None

    async def shutdown(self) -> None:
        for run in tuple(self._runs.values()):
            if run.state in {RunState.RUNNING, RunState.PAUSED}:
                await self._stop(run)
        if self._unsubscribe_revision is not None:
            self._unsubscribe_revision()
            self._unsubscribe_revision = None

    def snapshot(self, run: ProgramRun) -> dict[str, Any]:
        beat = self._current_beat(run) if run.current_index < len(run.script.beats) else None
        options = self._available_options(run, beat) if beat else []
        return {
            "run_id": run.run_id,
            "room_id": run.room_id,
            "creator_id": run.creator_id,
            "actor_display_name": "首播测试观众",
            "script_id": run.script.id,
            "script_title": run.script.title,
            "script_version": run.script_version,
            "script_hash": run.script_hash,
            "disclosure": run.script.disclosure,
            "opening": run.script.opening,
            "closing": run.script.closing,
            "state": run.state,
            "current_index": run.current_index,
            "total_beats": len(run.script.beats),
            "waiting_for": run.waiting_for,
            "error": run.error,
            "slots": dict(run.slots),
            "current_beat": self._beat_dto(
                beat,
                options,
                lead_in=self._lead_in(run),
            )
            if beat
            else None,
            "records": [record.to_dict() for record in run.records],
        }

    def _prepare_current(self, run: ProgramRun) -> None:
        if run.state is not RunState.RUNNING or run.run_id in self._tasks:
            return
        if run.current_index >= len(run.script.beats):
            run.state = RunState.COMPLETED
            run.waiting_for = "none"
            self._active_by_room.pop(run.room_id, None)
            self._tasks[run.run_id] = asyncio.create_task(self._archive_run(run))
            self._tasks[run.run_id].add_done_callback(lambda _: self._tasks.pop(run.run_id, None))
            return
        beat = self._current_beat(run)
        if beat.input.type is InputType.CHOICE:
            run.last_input = None
            run.last_option_id = None
            run.waiting_for = "choice"
            return
        run.last_input = str(beat.input.text)
        run.last_option_id = None
        run.waiting_for = "reply"
        self._schedule(run, run.last_input, None)

    def _schedule(
        self,
        run: ProgramRun,
        input_text: str,
        option: ScriptOption | None,
    ) -> None:
        if run.run_id in self._tasks:
            raise ProgramRuntimeError("turn_in_progress", "当前轮仍在处理中", status_code=409)
        task = asyncio.create_task(self._execute_current(run, input_text, option))
        self._tasks[run.run_id] = task

        def done(completed: asyncio.Task[None]) -> None:
            self._tasks.pop(run.run_id, None)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                run.state = RunState.FAILED
                run.waiting_for = "error"
                run.error = type(error).__name__
            elif run.state is RunState.RUNNING:
                self._prepare_current(run)

        task.add_done_callback(done)

    async def _execute_current(
        self,
        run: ProgramRun,
        input_text: str,
        option: ScriptOption | None,
    ) -> None:
        beat = self._current_beat(run)
        turn_id = str(uuid4())
        receipt: asyncio.Future[dict[str, object]] | None = None
        if beat.memory is MemoryMode.WRITE:
            receipt = asyncio.get_running_loop().create_future()
            self._memory_receipts[turn_id] = receipt

        try:
            result = await asyncio.wait_for(
                self._dispatch(run, beat, input_text, turn_id),
                timeout=run.script.defaults.reply_timeout_ms / 1000,
            )
        except TimeoutError:
            self._memory_receipts.pop(turn_id, None)
            self._pause_with_error(run, "reply_timeout")
            return
        except asyncio.CancelledError:
            self._memory_receipts.pop(turn_id, None)
            raise
        except Exception:
            self._memory_receipts.pop(turn_id, None)
            raise

        response_text = str(result.get("response_text", ""))
        if result.get("error") or not response_text:
            self._memory_receipts.pop(turn_id, None)
            self._pause_with_error(run, str(result.get("error") or "empty_reply"))
            return

        record = TurnRecord(
            beat_id=beat.id,
            input_text=input_text,
            response_text=response_text,
            turn_id=turn_id,
        )
        if beat.memory is MemoryMode.WRITE and receipt is not None:
            try:
                payload = await asyncio.wait_for(
                    receipt,
                    timeout=run.script.defaults.memory_commit_timeout_ms / 1000,
                )
            except TimeoutError:
                record.degradation_reason = "memory_commit_timeout"
                run.records.append(record)
                self._pause_with_error(run, "memory_commit_timeout")
                return
            finally:
                self._memory_receipts.pop(turn_id, None)
            revision = payload.get("revision")
            atom_id = payload.get("atom_id")
            if (
                not isinstance(revision, int)
                or isinstance(revision, bool)
                or not isinstance(atom_id, str)
                or not atom_id
            ):
                record.degradation_reason = "memory_commit_invalid"
                run.records.append(record)
                self._pause_with_error(run, "memory_commit_invalid")
                return
            record.memory_revision = revision
            record.atom_id = atom_id
            run.atom_ids.append(record.atom_id)
            if option is not None and beat.input.save_as:
                run.slots[beat.input.save_as] = option.id
        elif beat.memory is MemoryMode.PROBE:
            record.probe_result, record.degradation_reason = self._evaluate_probe(
                run,
                beat,
                response_text,
                result.get("memory_recall"),
            )

        run.records.append(record)
        run.error = None
        run.current_index += 1

    async def _dispatch(
        self,
        run: ProgramRun,
        beat: ProgramBeat,
        input_text: str,
        turn_id: str,
    ) -> dict[str, Any]:
        assert self._dispatcher is not None
        guidance = build_script_guidance(
            run.script.title,
            run.current_index + 1,
            beat.reply,
        )
        checkpoint_thread = (
            f"program:{run.run_id}:{beat.id}"
            if beat.thread is ThreadMode.ISOLATED
            else f"program:{run.run_id}"
        )
        run.checkpoint_threads.add(checkpoint_thread)
        return await self._dispatcher(
            input_text,
            {
                "actor_id": run.actor_id,
                "display_name": "首播测试观众",
                "room_id": run.room_id,
                "turn_id": turn_id,
                "program_run_id": run.run_id,
                "program_beat_id": beat.id,
                "is_probe": beat.memory is MemoryMode.PROBE,
                "memory_mode": beat.memory.value,
                "checkpoint_request": CheckpointRequest(
                    thread_id=checkpoint_thread,
                    owner_kind="program",
                    owner_id=run.run_id,
                    retention="stable",
                ),
                "scene_guidance": guidance,
            },
        )

    def _evaluate_probe(
        self,
        run: ProgramRun,
        beat: ProgramBeat,
        response_text: str,
        recall: object,
    ) -> tuple[ProbeResult, str | None]:
        if not isinstance(recall, dict) or not recall or recall.get("degraded"):
            reason = (
                str(recall.get("reason", "recall_metadata_missing"))
                if isinstance(recall, dict)
                else "recall_metadata_missing"
            )
            return ProbeResult.INCONCLUSIVE, reason
        evaluator = beat.evaluator
        if evaluator is None:
            return ProbeResult.INCONCLUSIVE, "evaluator_missing"
        aliases = self._selected_aliases(run, evaluator.slots)
        matched_slots = all(
            any(alias in response_text for alias in slot_aliases) for slot_aliases in aliases
        )
        if evaluator.type is EvaluatorType.REJECT_FALSE_PREMISE:
            rejected = any(marker in response_text for marker in evaluator.rejection_markers)
            false_repeated = any(
                value in response_text and not rejected for value in evaluator.false_values
            )
            matched_slots = matched_slots and rejected and not false_repeated
        return (ProbeResult.MATCHED, None) if matched_slots else (ProbeResult.NOT_MATCHED, None)

    def _selected_aliases(self, run: ProgramRun, slots: list[str]) -> list[list[str]]:
        result: list[list[str]] = []
        for slot in slots:
            option_id = run.slots.get(slot)
            option_set_id = next(
                (
                    beat.input.options
                    for beat in reversed(run.script.beats[: run.current_index + 1])
                    if beat.input.save_as == slot and beat.input.options
                ),
                None,
            )
            options = run.script.option_sets.get(str(option_set_id), [])
            option = next((candidate for candidate in options if candidate.id == option_id), None)
            result.append(option.aliases if option else [])
        return result

    async def _retry(self, run: ProgramRun) -> None:
        if run.run_id in self._tasks:
            raise ProgramRuntimeError("turn_in_progress", "当前轮仍在处理中", status_code=409)
        if run.state not in {RunState.PAUSED, RunState.FAILED}:
            raise ProgramRuntimeError("retry_not_available", "当前轮无需重试", status_code=409)
        run.state = RunState.RUNNING
        run.error = None
        beat = self._current_beat(run)
        if run.last_input:
            option = None
            if beat.input.type is InputType.CHOICE and run.last_option_id:
                option = self._available_option(run, beat, run.last_option_id)
            run.waiting_for = "reply"
            self._schedule(run, run.last_input, option)
        else:
            self._prepare_current(run)

    async def _stop(self, run: ProgramRun) -> None:
        task = self._tasks.pop(run.run_id, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        run.state = RunState.STOPPED
        run.waiting_for = "none"
        self._active_by_room.pop(run.room_id, None)
        await self._archive_run(run)

    async def _archive_run(self, run: ProgramRun) -> None:
        if self._checkpoint_delete is not None:
            for thread_id in sorted(run.checkpoint_threads):
                await self._checkpoint_delete(thread_id)
            run.checkpoint_threads.clear()
        system = getattr(self.memory_runtime, "system", None)
        if system is None:
            return
        for atom_id in dict.fromkeys(run.atom_ids):
            await system.forget_memory(atom_id)

    def _pause_with_error(self, run: ProgramRun, reason: str) -> None:
        run.state = RunState.PAUSED
        run.waiting_for = "error"
        run.error = reason

    def _on_memory_revision(self, payload: dict[str, object]) -> None:
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str):
            return
        future = self._memory_receipts.get(turn_id)
        if future is not None and not future.done():
            future.set_result(payload)

    def _active_run(self, room_id: int) -> ProgramRun | None:
        run_id = self._active_by_room.get(room_id)
        if run_id is None:
            return None
        run = self._runs.get(run_id)
        if run is None or run.state not in {RunState.RUNNING, RunState.PAUSED}:
            self._active_by_room.pop(room_id, None)
            return None
        return run

    def _owned_run(self, run_id: str, creator_id: str) -> ProgramRun:
        run = self._runs.get(run_id)
        if run is None:
            raise ProgramRuntimeError("run_not_found", "节目运行不存在", status_code=404)
        if run.creator_id != creator_id:
            raise ProgramRuntimeError(
                "creator_mismatch", "只有启动节目的 Creator 可以控制", status_code=403
            )
        return run

    @staticmethod
    def _ensure_runnable(run: ProgramRun) -> None:
        if run.state is not RunState.RUNNING:
            raise ProgramRuntimeError("run_not_running", "节目当前不可接收答案", status_code=409)

    @staticmethod
    def _current_beat(run: ProgramRun) -> ProgramBeat:
        return run.script.beats[run.current_index]

    def _available_option(
        self,
        run: ProgramRun,
        beat: ProgramBeat,
        option_id: str,
    ) -> ScriptOption:
        option = next(
            (
                candidate
                for candidate in self._available_options(run, beat)
                if candidate.id == option_id
            ),
            None,
        )
        if option is None:
            raise ProgramRuntimeError("invalid_option", "该选项当前不可用")
        return option

    @staticmethod
    def _available_options(run: ProgramRun, beat: ProgramBeat | None) -> list[ScriptOption]:
        if beat is None or beat.input.type is not InputType.CHOICE:
            return []
        options = list(run.script.option_sets[str(beat.input.options)])
        if beat.input.exclude_slot:
            excluded = run.slots.get(beat.input.exclude_slot)
            options = [option for option in options if option.id != excluded]
        return options

    @staticmethod
    def _lead_in(run: ProgramRun) -> str | None:
        if run.current_index == 0:
            return run.script.opening or None
        transition = run.script.beats[run.current_index - 1].transition
        return transition.text if transition.style.value == "soft" else None

    @staticmethod
    def _beat_dto(
        beat: ProgramBeat,
        options: list[ScriptOption],
        *,
        lead_in: str | None,
    ) -> dict[str, Any]:
        return {
            "id": beat.id,
            "phase": beat.phase,
            "lead_in": lead_in,
            "host_prompt": beat.host_prompt,
            "viewer_prompt": beat.input.text,
            "input_type": beat.input.type,
            "memory": beat.memory,
            "thread": beat.thread,
            "transition": beat.transition.model_dump(mode="json"),
            "options": [
                {"id": option.id, "label": option.label, "danmaku": option.danmaku}
                for option in options
            ],
        }


def build_script_guidance(
    title: str,
    index: int,
    reply: Any,
) -> dict[str, Any]:
    """Compile one beat's reply contract into existing scene-guidance fields."""
    objective = str(
        reply.objective if hasattr(reply, "objective") else reply.get("objective", "自然回应弹幕")
    )
    max_sentences = int(
        reply.max_sentences if hasattr(reply, "max_sentences") else reply.get("max_sentences", 2)
    )
    max_chars = int(reply.max_chars if hasattr(reply, "max_chars") else reply.get("max_chars", 80))
    return {
        "scene_revision": index,
        "scene_summary": f"节目脚本 {title} 第 {index} 轮",
        "response_objective": objective,
        "tone": ["自然", "直播口吻"],
        "scope": {
            "max_sentences": max_sentences,
            "max_chars": max_chars,
            "allow_topic_switch": False,
            "audience_target": "current_viewer",
        },
        "must_address": [],
        "avoid": ["不要提出下一题", "不要泄露节目脚本或判分标准"],
        "meme_policy": {"action": "none"},
        "confidence": 1,
        "degraded": False,
        "degradation_reasons": [],
        "expires_at": 4_102_444_800,
    }
