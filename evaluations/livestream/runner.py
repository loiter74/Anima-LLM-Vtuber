"""Transport and injectable full-stack livestream replay evaluation runner."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, Literal

import psutil

from animetta.config import ReplyPolicyConfig
from animetta.services.bilibili import (
    HIGH_HEAT_BURSTS,
    BurstWindow,
    DanmakuMessage,
    DanmakuReplyRuntime,
    LivestreamEvent,
    LivestreamSession,
    ReplayDanmakuGateway,
    ReplayTimeline,
    ReplyCandidate,
    ReplySubmissionResult,
)

from .dataset import DatasetValidator
from .reporting import ConversationRecord, calculate_hard_gates, summarize_origin_results

EvaluationMode = Literal["transport", "full"]
EvaluationReplyProcessor = Callable[[ReplyCandidate], Awaitable[str | None]]


class ResourceMonitor:
    """Collect process RSS samples and calculate the approved resource evidence."""

    def __init__(
        self,
        pid: int | None = None,
        *,
        sampler: Callable[[], float] | None = None,
        target_identity: str | None = None,
    ) -> None:
        if pid is not None and sampler is not None:
            raise ValueError("resource monitor accepts either pid or sampler, not both")
        process_pid = pid or os.getpid()
        self._process = psutil.Process(process_pid) if sampler is None else None
        self._sampler = sampler
        self._target_identity = target_identity or f"process:{process_pid}"
        self._started = time.monotonic()
        self._samples: list[tuple[float, float]] = []

    def sample(self) -> None:
        elapsed = time.monotonic() - self._started
        if self._sampler is not None:
            rss_mb = float(self._sampler())
        else:
            assert self._process is not None
            rss_mb = self._process.memory_info().rss / (1024 * 1024)
        self._samples.append((elapsed, rss_mb))

    def evidence(self) -> dict[str, Any]:
        if not self._samples:
            self.sample()
        warm = [sample for sample in self._samples if sample[0] >= 600]
        slope = _linear_slope_mb_per_hour(warm) if len(warm) >= 2 else 0.0
        baseline = warm[0][1] if warm else self._samples[0][1]
        end = self._samples[-1][1]
        return {
            "target": self._target_identity,
            "sample_count": len(self._samples),
            "warmup_complete": bool(warm),
            "baseline_rss_mb": round(baseline, 3),
            "end_rss_mb": round(end, 3),
            "rss_slope_mb_per_hour": round(max(0.0, slope), 3),
            "end_to_baseline_ratio": round(end / baseline, 6) if baseline else 1.0,
        }


class EvaluationRunner:
    """Replay one validated dataset and persist a complete evidence bundle."""

    def __init__(
        self,
        dataset_dir: Path,
        output_dir: Path,
        *,
        mode: EvaluationMode = "transport",
        speed: float | None = None,
        burst_windows: Sequence[BurstWindow] = (),
        reply_processor: EvaluationReplyProcessor | None = None,
        resource_pid: int | None = None,
        resource_sampler: Callable[[], float] | None = None,
        resource_identity: str | None = None,
        safety_assessment: dict[str, Any] | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        if mode not in {"transport", "full"}:
            raise ValueError("mode must be transport or full")
        if mode == "full" and reply_processor is None:
            raise ValueError("full mode requires an injected reply_processor")
        if mode == "full" and resource_pid is None and resource_sampler is None:
            raise ValueError("full mode requires an Animetta server resource target")
        if duration_seconds is not None and duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        self.dataset_dir = Path(dataset_dir)
        self.output_dir = Path(output_dir)
        self.mode = mode
        self.speed = speed if speed is not None else (10.0 if mode == "transport" else 1.0)
        self.burst_windows = tuple(burst_windows)
        self.reply_processor = reply_processor
        self.resource_pid = resource_pid
        self.resource_sampler = resource_sampler
        self.resource_identity = resource_identity
        self.safety_assessment = dict(safety_assessment) if safety_assessment is not None else None
        self.duration_seconds = duration_seconds
        self._records: list[ConversationRecord] = []
        self._message_records: dict[int, ConversationRecord] = {}
        self._pending_sequences: dict[tuple[str, str], deque[int]] = defaultdict(deque)
        self._record_by_sequence: dict[int, ConversationRecord] = {}

    async def run(self) -> dict[str, Any]:
        validation = DatasetValidator().validate(self.dataset_dir)
        if not validation.valid:
            raise ValueError(f"dataset validation failed: {','.join(validation.error_codes)}")
        replay_events = validation.events
        if self.duration_seconds is not None:
            maximum_offset_ms = round(self.duration_seconds * 1000)
            replay_events = [
                event for event in validation.events if event.offset_ms <= maximum_offset_ms
            ]
        if not replay_events:
            raise ValueError("configured replay duration contains no events")
        if self.burst_windows:
            source_end_offset_ms = replay_events[-1].offset_ms
            burst_profile = ReplayTimeline(
                speed=self.speed,
                burst_windows=self.burst_windows,
            ).burst_profile(source_end_offset_ms)
            if not burst_profile["all_completed"]:
                incomplete = [
                    str(window["start_seconds"])
                    for window in burst_profile["windows"]
                    if not window["completed"]
                ]
                raise ValueError(
                    "dataset timeline does not cover configured burst windows at replay "
                    f"seconds: {','.join(incomplete)}"
                )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        gateway = ReplayDanmakuGateway(
            replay_events,
            speed=self.speed,
            burst_windows=self.burst_windows,
        )
        policy = self._policy()
        runtime = DanmakuReplyRuntime(
            policy,
            self._process_reply,
            terminal_drop_sink=self._record_terminal_drop,
        )
        statuses: list[dict[str, object]] = []

        async def status_sink(snapshot: dict[str, object]) -> None:
            statuses.append(snapshot)

        session = LivestreamSession(
            gateway_factory=lambda _room_id, _sessdata: gateway,
            status_sink=status_sink,
            raw_event_sink=self._record_event,
            raw_message_sink=self._record_display,
            reply_runtime=runtime,
            reply_decision_sink=self._record_decision,
        )
        monitor = ResourceMonitor(
            self.resource_pid,
            sampler=self.resource_sampler,
            target_identity=self.resource_identity,
        )
        monitor.sample()
        monitor_task = asyncio.create_task(
            self._sample_resources(monitor),
            name="livestream-eval-resource-monitor",
        )
        uncaught_exceptions = 0
        crashed = False
        queue_recovered = False
        queue_depth_at_recovery_deadline = 0
        queue_recovery_started = time.monotonic()
        cleanup_started = queue_recovery_started
        try:
            await session.set_room(1)
            completed = await asyncio.to_thread(
                gateway.wait_until_complete, self._replay_timeout(replay_events)
            )
            if not completed:
                raise TimeoutError("replay did not complete within its bounded schedule")
            queue_recovery_started = time.monotonic()
            try:
                await self._wait_for_callbacks_and_replies(
                    session,
                    runtime,
                    len(replay_events),
                )
            except TimeoutError:
                queue_recovered = False
            else:
                queue_recovered = True
            queue_depth_at_recovery_deadline = runtime.metrics.queue_depth
            queue_recovery_seconds = time.monotonic() - queue_recovery_started
            monitor.sample()
        except Exception:
            uncaught_exceptions += 1
            crashed = True
            raise
        finally:
            cleanup_started = time.monotonic()
            await session.stop()
            await runtime.close()
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
            monitor.sample()
        cleanup_seconds = time.monotonic() - cleanup_started
        residual_tasks = (
            session.callback_task_count
            + int(gateway.thread_alive)
            + int(runtime.worker_running)
            + gateway.pending_callback_count
        )
        reply_metrics = session.metrics
        evidence: dict[str, Any] = {
            "schema_version": 1,
            "dataset_id": validation.manifest["dataset_id"],
            "heat_tier": validation.manifest["heat_tier"],
            "mode": self.mode,
            "speed": self.speed,
            "input_events": len(replay_events),
            "dataset_duration_seconds": validation.manifest["duration_ms"] / 1000,
            "source_duration_seconds": (
                self.duration_seconds
                if self.duration_seconds is not None
                else validation.manifest["duration_ms"] / 1000
            ),
            "windowed": self.duration_seconds is not None,
            "gateway_callback_events": session.event_metrics.received,
            "event_metrics": {
                "received": session.event_metrics.received,
                "dispatched": session.event_metrics.dispatched,
                "received_by_type": session.event_metrics.received_by_type,
                "dispatched_by_type": session.event_metrics.dispatched_by_type,
                "callback_failures": session.event_metrics.callback_failures,
            },
            "replay": gateway.metrics.to_dict(),
            "reply": {
                "policy": policy.model_dump(mode="json"),
                "received": reply_metrics.received,
                "displayed": reply_metrics.displayed,
                "admitted": reply_metrics.admitted,
                "dropped": dict(reply_metrics.dropped),
                "admitted_dropped": dict(reply_metrics.admitted_dropped),
                "reply_success": reply_metrics.reply_success,
                "reply_failure": reply_metrics.reply_failure,
                "max_queue_depth": reply_metrics.max_queue_depth,
                "queue_depth_end": reply_metrics.queue_depth,
                "queue_depth_at_recovery_deadline": queue_depth_at_recovery_deadline,
                "queue_recovered": queue_recovered,
                "queue_recovery_seconds": round(queue_recovery_seconds, 6),
            },
            "lifecycle": {
                "cleanup_seconds": round(cleanup_seconds, 6),
                "residual_tasks": residual_tasks,
            },
            "runtime": {
                "uncaught_exceptions": uncaught_exceptions,
                "crashed": crashed,
                "stuck_reconnecting": bool(
                    statuses and statuses[-1].get("state") == "reconnecting"
                ),
            },
            "resources": monitor.evidence(),
            "safety": self.safety_assessment
            or (
                {
                    "status": "not_applicable",
                    "reason": "transport mode uses a deterministic non-production stub",
                    "severe_issues": None,
                    "privacy_leaks": None,
                    "misattributions": None,
                }
                if self.mode == "transport"
                else {
                    "status": "unassessed",
                    "severe_issues": None,
                    "privacy_leaks": None,
                    "misattributions": None,
                }
            ),
        }
        evidence["origin_results"] = summarize_origin_results(self._records)
        if self.mode == "full":
            processor_owner = getattr(self.reply_processor, "__self__", None)
            evidence_provider = getattr(processor_owner, "evidence", None)
            evidence["full_stack"] = (
                evidence_provider()
                if callable(evidence_provider)
                else {
                    "completed": reply_metrics.reply_success,
                    "sentence_deliveries": 0,
                    "audio_deliveries": 0,
                    "live2d_deliveries": 0,
                    "control_completions": 0,
                }
            )
        evidence["hard_gates"] = calculate_hard_gates(evidence)
        self._write_evidence(evidence)
        return evidence

    async def _record_event(
        self,
        event: LivestreamEvent,
        _room_id: int,
        _generation_id: int,
    ) -> None:
        record = ConversationRecord(
            sequence=event.sequence,
            offset_ms=event.offset_ms,
            event_type=event.event_type.value,
            actor_id=event.actor_id,
            input_text=event.text,
            origin=str(event.payload.get("origin", "real")),
            source_sequence=(
                int(event.payload["source_sequence"])
                if isinstance(event.payload.get("source_sequence"), int)
                else None
            ),
            intent=str(event.payload.get("intent", "")),
            scenario=(
                str(event.payload["scenario"])
                if event.payload.get("scenario") is not None
                else None
            ),
            parent_sequence=(
                int(event.payload["parent_sequence"])
                if isinstance(event.payload.get("parent_sequence"), int)
                else None
            ),
        )
        self._records.append(record)
        self._record_by_sequence[event.sequence] = record
        if event.to_danmaku_message() is not None:
            self._pending_sequences[(event.actor_id, event.text)].append(event.sequence)

    async def _record_display(self, message: DanmakuMessage, _room_id: int) -> None:
        pending = self._pending_sequences[(message.user_name, message.text)]
        if not pending:
            return
        record = self._record_by_sequence[pending.popleft()]
        record.displayed = True
        self._message_records[id(message)] = record

    async def _record_decision(
        self,
        message: DanmakuMessage,
        result: ReplySubmissionResult,
        _room_id: int,
    ) -> None:
        record = self._message_records.get(id(message))
        if record is None:
            return
        record.admitted = result.admitted
        record.drop_reason = None if result.admitted else result.reason

    def _record_terminal_drop(self, candidate: ReplyCandidate, reason: str) -> None:
        record = self._message_records.get(id(candidate.message))
        if record is not None:
            record.drop_reason = reason

    async def _process_reply(self, candidate: ReplyCandidate) -> None:
        record = self._message_records.get(id(candidate.message))
        started = time.monotonic()
        try:
            if self.mode == "transport":
                reply = f"stub:{candidate.message.text}"
            else:
                assert self.reply_processor is not None
                reply = await self.reply_processor(candidate)
        except Exception as exc:
            if record is not None:
                record.processing_error = type(exc).__name__
            raise
        if record is not None:
            record.reply_text = reply or ""
            record.delivery_latency_ms = round((time.monotonic() - started) * 1000, 3)

    async def _wait_for_callbacks_and_replies(
        self,
        session: LivestreamSession,
        runtime: DanmakuReplyRuntime,
        event_count: int,
    ) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            processed = (
                runtime.metrics.reply_success
                + runtime.metrics.reply_failure
                + sum(runtime.metrics.admitted_dropped.values())
            )
            if (
                session.event_metrics.received == event_count
                and session.callback_task_count == 0
                and runtime.metrics.queue_depth == 0
                and processed >= runtime.metrics.admitted
            ):
                return
            await asyncio.sleep(0.01)
        raise TimeoutError("reply queue did not recover within 60 seconds")

    async def _sample_resources(self, monitor: ResourceMonitor) -> None:
        while True:
            await asyncio.sleep(30)
            monitor.sample()

    def _write_evidence(self, evidence: dict[str, Any]) -> None:
        (self.output_dir / "evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        with (self.output_dir / "conversation.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as handle:
            for record in sorted(self._records, key=lambda item: item.sequence):
                handle.write(
                    json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
                )

    def _replay_timeout(self, events: list[LivestreamEvent]) -> float:
        if not events:
            return 5.0
        return max(5.0, events[-1].offset_ms / 1000 / self.speed + 10)

    def _policy(self) -> ReplyPolicyConfig:
        if self.mode == "full":
            return ReplyPolicyConfig(
                max_replies_per_minute=1,
                max_message_age_seconds=120,
            )
        return ReplyPolicyConfig(
            enabled=True,
            max_replies_per_minute=60,
            max_queue_size=20,
            max_message_age_seconds=300,
            per_user_cooldown_seconds=0,
            duplicate_window_seconds=0,
            ordinary_sample_rate=1.0,
            reply_to_gifts=True,
            reply_to_super_chat=True,
        )


def default_bursts(enabled: bool) -> Sequence[BurstWindow]:
    return HIGH_HEAT_BURSTS if enabled else ()


def _linear_slope_mb_per_hour(samples: list[tuple[float, float]]) -> float:
    if len(samples) < 2:
        return 0.0
    mean_x = sum(sample[0] for sample in samples) / len(samples)
    mean_y = sum(sample[1] for sample in samples) / len(samples)
    denominator = sum((sample[0] - mean_x) ** 2 for sample in samples)
    if denominator == 0:
        return 0.0
    slope_per_second = (
        sum((elapsed - mean_x) * (rss - mean_y) for elapsed, rss in samples) / denominator
    )
    return slope_per_second * 3600
