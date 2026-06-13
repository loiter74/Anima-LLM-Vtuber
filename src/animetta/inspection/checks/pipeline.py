"""Pipeline smoke test — end-to-end conversation via Socket.IO.

Connects to the Anima backend via Socket.IO client, sends a test message,
collects all received events, and verifies that the full conversation
pipeline (LLM → TTS → emotion → output) produced the expected events.

Actual event names verified against the codebase's emit() calls in:
  - orchestration/graph/output_node.py  (expression, audio_with_expression, sentence, control)
  - orchestration/graph/asr_node.py     (transcript)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import socketio
from loguru import logger

from ..models import CheckResult

# ── Constants ────────────────────────────────────────────────────────

BACKEND_URL = "http://localhost:12394"
CONNECTION_TIMEOUT = 5.0  # seconds
COLLECTION_DURATION = 5.0  # seconds — events arrive as soon as LLM+TTS finish

# Verified against actual codebase emit() calls (see module docstring).
# These are the core events a text-mode conversation pipeline must produce.
EXPECTED_EVENTS: frozenset[str] = frozenset({
    "expression",            # emotion analysis result (output_node.py:97)
    "audio_with_expression", # TTS audio data (output_node.py:163)
    "sentence",              # LLM text response (output_node.py:59,62)
})


# ── Public API ───────────────────────────────────────────────────────


async def check_conversation_pipeline() -> CheckResult:
    """Run an end-to-end pipeline smoke test via Socket.IO.

    Connects as a client, sends a test message, collects all events
    for COLLECTION_DURATION seconds, then verifies that the expected
    core pipeline events were received.

    Returns:
        CheckResult.passed if all EXPECTED_EVENTS received.
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
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error("[inspection:pipeline] Connection timed out")
            return CheckResult.failed(
                name="pipeline/conversation",
                duration_ms=round(duration_ms, 1),
                error=f"Connection to {BACKEND_URL} timed out after {CONNECTION_TIMEOUT}s",
            )

        # ── Send test message ─────────────────────────────────────
        await sio.emit("chat:text_input", {"text": "[inspection] ping", "mode": "text"})
        logger.info("[inspection:pipeline] Sent test message, collecting events...")

        # ── Wait for pipeline to process ──────────────────────────
        await asyncio.sleep(COLLECTION_DURATION)

        # ── Disconnect ────────────────────────────────────────────
        await sio.disconnect()
        logger.info("[inspection:pipeline] Disconnected")

        # ── Evaluate results ──────────────────────────────────────
        missing = EXPECTED_EVENTS - received_events
        duration_ms = (time.perf_counter() - start_time) * 1000

        if not missing:
            logger.info(
                f"[inspection:pipeline] PASSED — all {len(EXPECTED_EVENTS)} "
                f"expected events received: {sorted(received_events)}"
            )
            return CheckResult.passed(
                name="pipeline/conversation",
                duration_ms=round(duration_ms, 1),
                received=sorted(received_events),
                missing=[],
            )

        logger.warning(
            f"[inspection:pipeline] FAILED — missing events: {sorted(missing)}. "
            f"Received: {sorted(received_events)}"
        )
        return CheckResult.failed(
            name="pipeline/conversation",
            duration_ms=round(duration_ms, 1),
            error=f"Missing expected events: {sorted(missing)}",
            received=sorted(received_events),
            missing=sorted(missing),
        )

    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.error(f"[inspection:pipeline] Unexpected error: {exc}")
        return CheckResult.failed(
            name="pipeline/conversation",
            duration_ms=round(duration_ms, 1),
            error=f"Exception during pipeline check: {exc}",
            received=sorted(received_events),
            missing=sorted(EXPECTED_EVENTS - received_events),
        )
