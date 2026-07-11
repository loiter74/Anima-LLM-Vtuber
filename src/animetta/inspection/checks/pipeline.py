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

# ── Constants ────────────────────────────────────────────────────────

BACKEND_URL = "http://localhost:12394"
CONNECTION_TIMEOUT = 5.0  # seconds
COLLECTION_DURATION = 5.0  # seconds — connection/probe events should arrive quickly
_MIN_DURATION_MS = 0.1

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


async def check_golden_conversation_pipeline() -> CheckResult:
    """Run a contained probe followed by one real correlated conversation."""
    started = time.perf_counter()
    client = socketio.AsyncClient(reconnection=False)
    phase = "probe"
    probe_leaks: list[str] = []
    real_events: list[tuple[str, dict[str, Any]]] = []
    terminal = asyncio.Event()
    conversation_id = str(uuid4())

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
        return CheckResult.passed(
            name="pipeline/conversation", duration_ms=_duration_ms_since(started),
            probe_contained=True, task_id=task_id, received=sorted(names),
        )
    except Exception as exc:
        return CheckResult.failed(
            name="pipeline/conversation", duration_ms=_duration_ms_since(started),
            error=f"golden pipeline failure: {type(exc).__name__}",
        )
    finally:
        if client.connected:
            await client.disconnect()
