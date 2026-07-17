"""Pure state machine and evidence helpers for the ten-minute golden soak."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from animetta.orchestration.prompting.roleplay_guard import detect_drift

IDENTITY_KEYS = ("message_id", "conversation_id", "task_id", "turn_id")
GOLDEN_EVENTS = {
    "chat:control",
    "chat:sentence",
    "chat:expression",
    "chat:live2d_action",
    "chat:audio_with_expression",
    "chat:audio_stream_start",
    "chat:audio_stream_chunk",
    "chat:audio_stream_end",
    "chat:subtitle_translation",
    "system:error",
}
_MARKERS = re.compile(
    r"<\|(?:assistant|system|think)\|>|\[affinity:|\[(?:happy|sad|angry|neutral|thinking)\]|```(?:json)?|normal_response|final_response",
    re.IGNORECASE,
)


class GateFailureError(RuntimeError):
    pass


@dataclass(slots=True)
class TurnTracker:
    identity: dict[str, str]
    started_at: float
    events: list[dict[str, Any]] = field(default_factory=list)
    final_text: str = ""
    text_ready_at: float | None = None
    audio_ready_at: float | None = None
    media_ready_at: float | None = None
    completion_count: int = 0
    expression_count: int = 0
    action_count: int = 0
    audio_count: int = 0
    audio_transport: str | None = None
    audio_stream_id: str | None = None
    audio_stream_next_sequence: int = 0
    audio_stream_chunk_count: int = 0
    audio_stream_status: str | None = None
    degradation_count: int = 0
    terminal_count: int = 0

    def accept(self, event: str, payload: dict[str, Any], now: float) -> None:
        if event not in GOLDEN_EVENTS:
            return
        missing = [key for key in IDENTITY_KEYS if key not in payload]
        if missing:
            raise GateFailureError(f"event_identity_missing:{event}:{','.join(missing)}")
        if any(payload[key] != self.identity[key] for key in IDENTITY_KEYS):
            raise GateFailureError(f"event_identity_mismatch:{event}")
        self.events.append({"event": event, "at": now, "payload": _safe_payload(payload)})
        if event == "chat:sentence":
            if payload.get("text"):
                if self.final_text:
                    raise GateFailureError("duplicate_authored_response")
                self.final_text = str(payload["text"])
                self.text_ready_at = now
            if payload.get("is_complete") or payload.get("text") == "":
                self.completion_count += 1
        elif event == "chat:expression":
            self.expression_count += 1
        elif event == "chat:live2d_action":
            self.action_count += 1
        elif event == "chat:audio_with_expression":
            if not payload.get("audio_data") or not payload.get("volumes"):
                raise GateFailureError("empty_or_silent_audio")
            if self.audio_transport is not None:
                raise GateFailureError("multiple_audio_transports")
            self.audio_transport = "complete_audio"
            self.audio_ready_at = now
            self.audio_count += 1
        elif event == "chat:audio_stream_start":
            if self.audio_transport is not None or self.audio_stream_id is not None:
                raise GateFailureError("multiple_audio_transports")
            if (
                not payload.get("stream_id")
                or payload.get("format") != "pcm_s16le"
                or payload.get("sample_rate") != 24_000
                or payload.get("channels") != 1
            ):
                raise GateFailureError("invalid_audio_stream_start")
            self.audio_transport = "pcm_stream"
            self.audio_stream_id = str(payload["stream_id"])
        elif event == "chat:audio_stream_chunk":
            if payload.get("stream_id") != self.audio_stream_id:
                raise GateFailureError("audio_stream_identity_mismatch")
            if payload.get("sequence") != self.audio_stream_next_sequence:
                raise GateFailureError("audio_stream_sequence_mismatch")
            if not payload.get("audio_data"):
                raise GateFailureError("empty_audio_stream_chunk")
            if self.audio_ready_at is None:
                self.audio_ready_at = now
            self.audio_stream_chunk_count += 1
            self.audio_stream_next_sequence += 1
        elif event == "chat:audio_stream_end":
            if payload.get("stream_id") != self.audio_stream_id:
                raise GateFailureError("audio_stream_identity_mismatch")
            if self.audio_stream_status is not None:
                raise GateFailureError("duplicate_audio_stream_end")
            if payload.get("final_sequence") != self.audio_stream_next_sequence - 1:
                raise GateFailureError("audio_stream_final_sequence_mismatch")
            status = str(payload.get("status") or "")
            if status not in {"completed", "failed", "cancelled"}:
                raise GateFailureError("invalid_audio_stream_status")
            if status == "completed" and self.audio_stream_chunk_count < 1:
                raise GateFailureError("empty_audio_stream")
            self.audio_stream_status = status
            if status == "completed":
                self.audio_count += 1
        elif event == "chat:control" and payload.get("type") == "media-degraded":
            self.degradation_count += 1
        elif event == "chat:control" and payload.get("signal") == "conversation-end":
            self.terminal_count += 1
            self.media_ready_at = now
        elif event == "system:error" and payload.get("terminal"):
            raise GateFailureError(f"terminal_error:{payload.get('component', 'unknown')}")

    def finalize(self) -> dict[str, Any]:
        if not self.final_text or self.completion_count != 1:
            raise GateFailureError("incomplete_text_delivery")
        if self.expression_count < 1 or self.action_count < 1 or self.terminal_count != 1:
            raise GateFailureError(
                "incomplete_performance_delivery:"
                f"expression={self.expression_count},"
                f"action={self.action_count},"
                f"terminal={self.terminal_count}"
            )
        if self.audio_stream_id is not None and self.audio_stream_status is None:
            raise GateFailureError("incomplete_audio_stream")
        degraded = self.degradation_count == 1
        if degraded and self.audio_count:
            raise GateFailureError("degraded_turn_emitted_audio")
        if not degraded and self.audio_count != 1:
            raise GateFailureError("non_degraded_turn_missing_audio")
        drift = detect_drift(self.final_text)
        markers = _MARKERS.findall(self.final_text)
        if drift:
            raise GateFailureError("roleplay_drift")
        if markers:
            raise GateFailureError("runtime_marker_leak")
        return {
            "identity": self.identity,
            "events": self.events,
            "safe_output": safe_excerpt(self.final_text),
            "text_ready_ms": round((self.text_ready_at - self.started_at) * 1000, 2),
            "audio_ready_ms": (
                round((self.audio_ready_at - self.started_at) * 1000, 2)
                if self.audio_ready_at is not None
                else None
            ),
            "media_ready_ms": round((self.media_ready_at - self.started_at) * 1000, 2),
            "audio_transport": self.audio_transport,
            "audio_chunk_count": self.audio_stream_chunk_count,
            "degraded": degraded,
            "drift": [],
            "marker_leak": [],
        }


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value / 100 * len(ordered)) - 1)
    return float(ordered[index])


def evaluate_audio_latency(
    turns: list[dict[str, Any]],
    *,
    p50_limit_ms: float,
    p95_limit_ms: float,
) -> dict[str, int | float | bool]:
    """Evaluate user-send to first-audio latency without hiding missing turns."""
    latencies = [
        float(value)
        for turn in turns
        if isinstance((value := turn.get("audio_ready_ms")), (int, float))
        and not isinstance(value, bool)
    ]
    p50_ms = percentile(latencies, 50)
    p95_ms = percentile(latencies, 95)
    complete = len(latencies) == len(turns) and bool(turns)
    passed = complete and p50_ms <= p50_limit_ms and p95_ms <= p95_limit_ms
    return {
        "turn_count": len(turns),
        "sample_count": len(latencies),
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "p50_limit_ms": float(p50_limit_ms),
        "p95_limit_ms": float(p95_limit_ms),
        "complete": complete,
        "passed": passed,
    }


def evaluate_degradation_budget(turns: list[dict[str, Any]]) -> tuple[bool, str]:
    degraded = [index for index, turn in enumerate(turns) if turn.get("degraded")]
    if len(degraded) > 1:
        return False, "more_than_one_degradation"
    if degraded and degraded[0] == len(turns) - 1:
        return False, "degradation_recovery_unproven"
    if degraded and turns[degraded[0] + 1].get("degraded"):
        return False, "consecutive_degradation"
    return True, "within_budget"


def scan_sanitized_logs(text: str) -> list[str]:
    forbidden = re.compile(
        r"Traceback|\bERROR\b|MockLLM|MockTTS|provider\s+(?:substitution|fallback)|orphan(?:ed)?\s+task",
        re.IGNORECASE,
    )
    return [
        f"line:{index}:{match.group(0)}"
        for index, line in enumerate(text.splitlines(), 1)
        if (match := forbidden.search(line))
    ]


class EvidenceWriter:
    def __init__(self, path: Path, initial: dict[str, Any]) -> None:
        self.path = path
        self.data = initial
        self.flush()

    def update(self, **values: Any) -> None:
        self.data.update(values)
        self.flush()

    def append_turn(self, turn: dict[str, Any]) -> None:
        self.data.setdefault("turns", []).append(turn)
        self.flush()

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = datetime.now(UTC).isoformat()
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def safe_excerpt(text: str) -> str:
    return text.replace("\n", " ")[:120]


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        *IDENTITY_KEYS,
        "seq",
        "is_complete",
        "signal",
        "type",
        "status",
        "component",
        "phase",
        "reason",
        "retryable",
        "format",
        "emotion",
        "stream_id",
        "sequence",
        "final_sequence",
        "sample_rate",
        "channels",
    }
    result = {key: payload[key] for key in allowed if key in payload}
    if payload.get("text"):
        result["text_excerpt"] = safe_excerpt(str(payload["text"]))
    if payload.get("audio_data"):
        result["audio_bytes_b64"] = len(str(payload["audio_data"]))
    if isinstance(payload.get("volumes"), list):
        result["volume_samples"] = len(payload["volumes"])
    return result
