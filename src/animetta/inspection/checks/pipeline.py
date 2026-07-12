"""Pipeline smoke test — Socket.IO conversation ingress via filtered probe.

Connects to the Anima backend via Socket.IO client, sends a test message,
collects all received events, and verifies that the backend connection and
probe containment boundary are healthy.

Inspection probes are intentionally filtered before LLM dispatch by
core/message_filter.py, so this check must not expect LLM/TTS output events.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

import socketio
from loguru import logger

from animetta.orchestration.socket_events import EVENTS

from ..models import CheckResult
from ..runtime import InspectionRuntime
from .metrics import controlled_metric_delta

# ── Constants ────────────────────────────────────────────────────────

BACKEND_URL = "http://localhost:12394"
CONNECTION_TIMEOUT = 5.0  # seconds
COLLECTION_DURATION = 5.0  # seconds — connection/probe events should arrive quickly
_MIN_DURATION_MS = 0.1

GOLDEN_TEXT_WORKFLOW = (
    "conversation_start",
    "personality",
    "reasoner",
    "anima_composer",
    "response_guard",
    "reply_output",
    "tts",
    "emotion",
    "performance_output",
    "conversation_finalizer",
)
STANDARD_TEXT_WORKFLOW = (
    "personality",
    "llm",
    "humor_rewrite",
    "humor_validation",
    "tts",
    "emotion",
    "output",
)

# Catalog-backed event used to inject the inspection probe.
PROBE_INPUT_EVENT = EVENTS["chat"]["text"]["name"]

# Required catalog-backed events for a filtered inspection probe.
EXPECTED_EVENTS: frozenset[str] = frozenset({
    EVENTS["system"]["connection_established"]["name"],
})

# If any of these arrive for an inspection probe, the probe leaked into output.
PROHIBITED_PROBE_EVENTS: frozenset[str] = frozenset({
    EVENTS["chat"]["sentence"]["name"],
    EVENTS["chat"]["expression"]["name"],
    EVENTS["chat"]["audio_with_expression"]["name"],
})


def _duration_ms_since(start_time: float) -> float:
    return round(max((time.perf_counter() - start_time) * 1000, _MIN_DURATION_MS), 1)


# ── Public API ───────────────────────────────────────────────────────


async def check_conversation_pipeline() -> CheckResult:
    """Run a Socket.IO conversation ingress smoke test.

    Connects as a client, sends a test message, collects all events
    for COLLECTION_DURATION seconds, then verifies that the expected
    connection event was received and the filtered probe did not reach
    LLM/TTS output events.

    Returns:
        CheckResult.passed if all EXPECTED_EVENTS received and no
        PROHIBITED_PROBE_EVENTS are received.
        CheckResult.failed with diagnostic detail otherwise.
    """
    start_time = time.perf_counter()

    received_events: set[str] = set()
    sio = socketio.AsyncClient()

    # ── Wildcard listener — captures every event name ──────────────
    @sio.on("*")
    async def catch_all(event: str, data: Any) -> None:  # noqa: ARG001
        received_events.add(event)

    try:
        # ── Connect with timeout ──────────────────────────────────
        try:
            await asyncio.wait_for(
                sio.connect(BACKEND_URL, transports=["websocket"]),
                timeout=CONNECTION_TIMEOUT,
            )
            logger.info("[inspection:pipeline] Connected to backend")
        except TimeoutError:
            logger.error("[inspection:pipeline] Connection timed out")
            return CheckResult.failed(
                name="pipeline/conversation",
                duration_ms=_duration_ms_since(start_time),
                error=f"Connection to {BACKEND_URL} timed out after {CONNECTION_TIMEOUT}s",
            )

        # ── Send test message ─────────────────────────────────────
        # ``is_inspection`` tags this payload so the chat handler drops it before
        # LLM dispatch (see core/message_filter.py). The textual
        # ``[inspection]`` prefix is a redundant backstop in case older code is
        # in play.
        await sio.emit(PROBE_INPUT_EVENT, {
            "text": "[inspection] ping",
            "mode": "text",
            "is_inspection": True,
        })
        logger.info("[inspection:pipeline] Sent test message, collecting events...")

        # ── Wait for pipeline to process ──────────────────────────
        await asyncio.sleep(COLLECTION_DURATION)

        # ── Disconnect ────────────────────────────────────────────
        await sio.disconnect()
        logger.info("[inspection:pipeline] Disconnected")

        # ── Evaluate results ──────────────────────────────────────
        missing = EXPECTED_EVENTS - received_events
        leaked = PROHIBITED_PROBE_EVENTS & received_events
        duration_ms = _duration_ms_since(start_time)

        if not missing and not leaked:
            logger.info(
                f"[inspection:pipeline] PASSED — all {len(EXPECTED_EVENTS)} "
                f"expected events received: {sorted(received_events)}"
            )
            return CheckResult.passed(
                name="pipeline/conversation",
                duration_ms=duration_ms,
                received=sorted(received_events),
                missing=[],
                leaked=[],
            )

        error_parts = []
        if missing:
            error_parts.append(f"missing expected events: {sorted(missing)}")
        if leaked:
            error_parts.append(f"probe leaked to output events: {sorted(leaked)}")
        logger.warning(
            f"[inspection:pipeline] FAILED — {'; '.join(error_parts)}. "
            f"Received: {sorted(received_events)}"
        )
        return CheckResult.failed(
            name="pipeline/conversation",
            duration_ms=duration_ms,
            error="; ".join(error_parts),
            received=sorted(received_events),
            missing=sorted(missing),
            leaked=sorted(leaked),
        )

    except Exception as exc:
        logger.error(f"[inspection:pipeline] Unexpected error: {exc}")
        return CheckResult.failed(
            name="pipeline/conversation",
            duration_ms=_duration_ms_since(start_time),
            error=f"Exception during pipeline check: {exc}",
            received=sorted(received_events),
            missing=sorted(EXPECTED_EVENTS - received_events),
            leaked=sorted(PROHIBITED_PROBE_EVENTS & received_events),
        )


async def check_golden_conversation_pipeline(
    runtime: InspectionRuntime | None = None,
) -> CheckResult:
    """Run a contained probe followed by one real correlated conversation."""
    started = time.perf_counter()
    client = socketio.AsyncClient(reconnection=False)
    phase = "probe"
    probe_leaks: list[str] = []
    real_events: list[tuple[str, dict[str, Any]]] = []
    terminal = asyncio.Event()
    conversation_id = str(uuid4())
    metrics_before = runtime.metrics_snapshot() if runtime is not None else None

    @client.on("*")
    async def capture(event: str, payload: Any = None) -> None:
        if not isinstance(payload, dict):
            return
        if phase == "probe" and event in PROHIBITED_PROBE_EVENTS:
            probe_leaks.append(event)
        elif phase == "real" and event.startswith(("chat:", "system:")):
            real_events.append((event, payload))
            if (
                event == EVENTS["chat"]["control"]["name"]
                and payload.get("signal") == "conversation-end"
            ):
                terminal.set()

    try:
        await asyncio.wait_for(
            client.connect(BACKEND_URL, transports=["websocket"]), CONNECTION_TIMEOUT
        )
        probe_task = str(uuid4())
        await client.emit(PROBE_INPUT_EVENT, {
            "text": "[inspection] ping", "message_id": str(uuid4()),
            "conversation_id": conversation_id, "task_id": probe_task,
            "turn_id": probe_task, "source": "text", "is_inspection": True,
            "is_acceptance": False,
        })
        await asyncio.sleep(COLLECTION_DURATION)
        if probe_leaks:
            return CheckResult.failed(
                name="pipeline/conversation", duration_ms=_duration_ms_since(started),
                error="inspection probe leaked", leaked=probe_leaks,
            )
        if runtime is not None and await runtime.observation_query.trace_detail(probe_task):
            return CheckResult.failed(
                name="pipeline/conversation",
                duration_ms=_duration_ms_since(started),
                error="inspection probe created canonical trace",
            )
        phase = "real"
        task_id = str(uuid4())
        identity = {
            "message_id": str(uuid4()), "conversation_id": conversation_id,
            "task_id": task_id, "turn_id": task_id,
        }
        await client.emit(PROBE_INPUT_EVENT, {
            **identity, "text": "请用一句话介绍你自己。", "source": "text",
            "is_inspection": False, "is_acceptance": True,
        })
        await asyncio.wait_for(terminal.wait(), timeout=60.0)
        required = {
            EVENTS["chat"]["sentence"]["name"], EVENTS["chat"]["expression"]["name"],
            EVENTS["chat"]["live2d_action"]["name"], EVENTS["chat"]["control"]["name"],
        }
        names = {event for event, _ in real_events}
        mismatched = [event for event, payload in real_events if event in required and any(
            payload.get(key) != value for key, value in identity.items()
        )]
        missing = required - names
        if missing or mismatched:
            return CheckResult.failed(
                name="pipeline/conversation", duration_ms=_duration_ms_since(started),
                error="real golden conversation contract failed",
                missing=sorted(missing), mismatched=mismatched,
            )
        validation: CheckResult | None = None
        if runtime is not None:
            readiness = runtime.readiness_snapshot()
            readiness_payload = (
                readiness.to_dict() if hasattr(readiness, "to_dict") else dict(readiness)
            )
            profile = readiness_payload.get("profile", "development")
            validation = await validate_observed_turn(
                runtime,
                task_id=task_id,
                client_events=real_events,
                expected_workflow=(
                    GOLDEN_TEXT_WORKFLOW
                    if profile == "golden"
                    else STANDARD_TEXT_WORKFLOW
                ),
                expected_llm_calls=2 if profile == "golden" else None,
                metrics_before=metrics_before,
            )
            if not validation.ok:
                return validation
        result_detail = dict(validation.detail) if validation is not None else {}
        result_detail.update({
            "probe_contained": True,
            "task_id": result_detail.get("task_id", task_id),
            "received": sorted(names),
        })
        return CheckResult.passed(
            name=(validation.name if validation is not None else "pipeline/conversation"),
            duration_ms=_duration_ms_since(started),
            **result_detail,
        )
    except Exception as exc:
        return CheckResult.failed(
            name="pipeline/conversation", duration_ms=_duration_ms_since(started),
            error=f"golden pipeline failure: {type(exc).__name__}",
        )
    finally:
        if client.connected:
            await client.disconnect()


async def validate_observed_turn(
    runtime: InspectionRuntime,
    *,
    task_id: str,
    client_events: list[tuple[str, dict[str, Any]]],
    expected_workflow: tuple[str, ...],
    expected_llm_calls: int | None = None,
    metrics_before: str | None = None,
) -> CheckResult:
    """Compare one client-visible turn with its canonical ledger and metric mirror."""
    started = time.perf_counter()
    detail = await _await_trace_detail(runtime, task_id)
    if detail is None:
        return CheckResult.failed(
            "pipeline/observed_turn",
            duration_ms=_duration_ms_since(started),
            error="canonical trace not found",
            task_id=task_id,
        )
    operations = list(detail.get("operations", []))
    workflow = tuple(
        operation.get("name")
        for operation in operations
        if operation.get("layer") == "workflow"
    )
    llm_calls = sum(
        operation.get("layer") == "service"
        and str(operation.get("name", "")).startswith("llm.")
        for operation in operations
    )
    mock_llm_calls = sum(
        operation.get("layer") == "service"
        and str(operation.get("name", "")).startswith("llm.")
        and operation.get("provider") == "mock"
        for operation in operations
    )
    memory_writes = [
        operation.get("name")
        for operation in operations
        if operation.get("layer") == "memory"
        and not operation.get("critical_path", True)
    ]
    ledger_events = {
        event.get("name")
        for event in detail.get("events", [])
        if event.get("direction") == "egress" and event.get("phase") == "delivered"
    }
    visible_events = {event for event, _payload in client_events}
    missing_delivery_evidence = visible_events - ledger_events
    tts_operations = [
        operation for operation in operations if operation.get("name") == "tts"
    ]
    tts_service_operations = [
        operation
        for operation in operations
        if operation.get("layer") == "service"
        and str(operation.get("name", "")).startswith("tts.")
    ]
    readiness = runtime.readiness_snapshot()
    readiness_payload = (
        readiness.to_dict() if hasattr(readiness, "to_dict") else dict(readiness)
    )
    tts_runtime = readiness_payload.get("components", {}).get("tts", {})
    real_tts_service_succeeded = any(
        operation.get("status") == "success"
        and operation.get("provider") not in {None, "", "mock"}
        for operation in tts_service_operations
    )
    runtime_tts_is_real = tts_runtime.get("provider") not in {None, "", "mock"}
    runtime_tts_evidence = bool(
        runtime_tts_is_real
        and (tts_runtime.get("ready") is True or tts_runtime.get("state") == "failed")
    )
    tts_evidence = bool(
        tts_operations
        and tts_operations[-1].get("status") in {"success", "degraded", "error"}
        and (real_tts_service_succeeded or runtime_tts_evidence)
    )
    issues: list[str] = []
    if workflow != expected_workflow:
        issues.append("workflow_topology_mismatch")
    if expected_llm_calls is not None and llm_calls != expected_llm_calls:
        issues.append("llm_call_count_mismatch")
    if mock_llm_calls:
        issues.append("mock_llm_call_observed")
    if memory_writes:
        issues.append("prohibited_memory_write")
    if missing_delivery_evidence:
        issues.append("client_ledger_event_mismatch")
    if not tts_evidence:
        issues.append("tts_evidence_missing")
    delta: dict[str, float] = {}
    if metrics_before is not None:
        for _ in range(50):
            delta = controlled_metric_delta(metrics_before, runtime.metrics_snapshot())
            if all(value > 0 for value in delta.values()):
                break
            await asyncio.sleep(0.1)
        if any(value <= 0 for value in delta.values()):
            issues.append("metrics_delta_missing")
    result_detail = {
        "task_id": task_id,
        "workflow": list(workflow),
        "llm_calls": llm_calls,
        "mock_llm_calls": mock_llm_calls,
        "memory_writes": memory_writes,
        "missing_delivery_evidence": sorted(missing_delivery_evidence),
        "tts_evidence": tts_evidence,
        "metrics_delta": delta,
    }
    if issues:
        return CheckResult.failed(
            "pipeline/observed_turn",
            duration_ms=_duration_ms_since(started),
            error="; ".join(issues),
            **result_detail,
        )
    return CheckResult.passed(
        "pipeline/observed_turn",
        duration_ms=_duration_ms_since(started),
        **result_detail,
    )


async def _await_trace_detail(
    runtime: InspectionRuntime,
    task_id: str,
) -> dict[str, Any] | None:
    for _ in range(50):
        detail = await runtime.observation_query.trace_detail(task_id)
        if detail is not None and detail.get("outcome") is not None:
            return dict(detail)
        await asyncio.sleep(0.1)
    detail = await runtime.observation_query.trace_detail(task_id)
    return dict(detail) if detail is not None else None
