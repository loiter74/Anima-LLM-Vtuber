#!/usr/bin/env python3
"""Probe one production Socket.IO turn for typed TTS degradation or audio."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import uuid4

import socketio

from animetta.acceptance.golden_soak import GateFailureError, TurnTracker

Expectation = Literal["degraded", "audio"]


class ReleaseTurnProbeError(RuntimeError):
    """A production turn did not satisfy its expected media contract."""


def validate_turn_result(result: Mapping[str, Any], *, expect: Expectation) -> None:
    """Validate text/Live2D continuity and the expected typed media outcome."""
    if not str(result.get("safe_output", "")).strip():
        raise ReleaseTurnProbeError("Release turn did not preserve authored text")
    if int(result.get("expression_count", 0)) < 1 or int(result.get("action_count", 0)) < 1:
        raise ReleaseTurnProbeError("Release turn did not preserve Live2D continuity")
    degraded = result.get("degraded") is True
    audio_count = int(result.get("audio_count", 0))
    degradation_count = int(result.get("degradation_count", 0))
    if expect == "degraded" and not (degraded and degradation_count == 1 and audio_count == 0):
        raise ReleaseTurnProbeError("Release turn did not emit one typed media degradation")
    if expect == "audio" and not (not degraded and degradation_count == 0 and audio_count == 1):
        raise ReleaseTurnProbeError("Release recovery turn did not emit exactly one audio event")


async def probe_turn(
    *,
    url: str,
    text: str,
    conversation_id: str,
    expect: Expectation,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Send one correlated acceptance turn and validate its terminal event set."""
    client = socketio.AsyncClient(reconnection=False)
    task_id = str(uuid4())
    identity = {
        "message_id": str(uuid4()),
        "conversation_id": conversation_id,
        "task_id": task_id,
        "turn_id": task_id,
    }
    tracker = TurnTracker(identity, time.perf_counter())
    terminal = asyncio.Event()
    asynchronous_failure: list[Exception] = []

    @client.on("*")
    async def capture(event: str, payload: Any = None) -> None:
        if not isinstance(payload, dict) or event == "system:connection_established":
            return
        if (
            event == "chat:control"
            and payload.get("type") == "control"
            and payload.get("text") == "start-mic"
        ):
            return
        try:
            tracker.accept(event, payload, time.perf_counter())
            if event == "chat:control" and payload.get("signal") == "conversation-end":
                terminal.set()
        except Exception as exc:
            asynchronous_failure.append(exc)
            terminal.set()

    await client.connect(url, transports=["websocket"], wait_timeout=15)
    try:
        await client.emit(
            "chat:text",
            {
                **identity,
                "text": text,
                "source": "text",
                "is_inspection": False,
                "is_acceptance": True,
            },
        )
        try:
            await asyncio.wait_for(terminal.wait(), timeout=timeout_seconds)
        except TimeoutError as exc:
            raise ReleaseTurnProbeError("Release turn timed out") from exc
        if asynchronous_failure:
            raise asynchronous_failure[0]
        result = tracker.finalize()
    except GateFailureError as exc:
        raise ReleaseTurnProbeError(str(exc)) from exc
    finally:
        if client.connected:
            await client.disconnect()

    result.update(
        {
            "status": "passed",
            "conversation_id": conversation_id,
            "task_id": task_id,
            "audio_count": tracker.audio_count,
            "degradation_count": tracker.degradation_count,
            "expression_count": tracker.expression_count,
            "action_count": tracker.action_count,
        }
    )
    validate_turn_result(result, expect=expect)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost")
    parser.add_argument("--text", required=True)
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--expect", choices=("degraded", "audio"), required=True)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(
            probe_turn(
                url=args.url,
                text=args.text,
                conversation_id=args.conversation_id,
                expect=args.expect,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except (OSError, ValueError, ReleaseTurnProbeError) as exc:
        print(
            json.dumps(
                {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
