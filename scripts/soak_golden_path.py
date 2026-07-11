#!/usr/bin/env python3
"""Run the real 600-second/12-turn July golden acceptance gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import socketio

from animetta.acceptance.golden_soak import (
    EvidenceWriter,
    GateFailureError,
    TurnTracker,
    evaluate_degradation_budget,
    percentile,
    scan_sanitized_logs,
)

PROMPTS = [
    "晚上好，简单介绍一下你自己。", "我今天工作有点累，你怎么看？",
    "延续刚才的话题，给我一个能马上执行的小建议。", "用你自己的世界观形容一次普通加班。",
    "讲一个不过分的职场冷笑话。", "你认为什么样的休息才算真正有效？",
    "还记得我刚才说累吗？把建议再具体一点。", "如果这里是一间酒馆，今晚的招牌饮料是什么？",
    "直接回答：明天第一件事应该做什么？", "保持你的角色口吻，鼓励我一句。",
    "总结我们刚才聊过的三个重点。", "最后用一句自然的话和我道晚安。",
]


async def _get_json(url: str) -> dict[str, Any]:
    def read() -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    return await asyncio.to_thread(read)


def _contains_mock(value: Any) -> bool:
    return "mock" in json.dumps(value, ensure_ascii=False, default=str).lower()


def _is_connection_bootstrap(event: str, payload: dict[str, Any]) -> bool:
    """Recognize the one legacy control frame emitted while a socket connects."""
    return (
        event == "chat:control"
        and payload.get("type") == "control"
        and payload.get("text") == "start-mic"
    )


def _revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
    except Exception:
        return "unknown"


async def run(args: argparse.Namespace, writer: EvidenceWriter) -> None:
    health, readiness = await asyncio.gather(
        _get_json(f"{args.url}/health"), _get_json(f"{args.url}/ready")
    )
    writer.update(health=health, readiness=readiness)
    if health.get("status") != "ok":
        raise GateFailureError("health_not_ok")
    if readiness.get("status") not in {"ready", "ok"} and readiness.get("ready") is not True:
        raise GateFailureError("golden_readiness_failed")
    if _contains_mock(readiness):
        raise GateFailureError("mock_provider_observed")

    client = socketio.AsyncClient(reconnection=False)
    active: TurnTracker | None = None
    terminal = asyncio.Event()
    disconnected: list[float] = []
    asynchronous_failure: list[Exception] = []

    @client.on("*")
    async def capture(event: str, payload: Any = None) -> None:
        nonlocal active
        if not isinstance(payload, dict) or event == "system:connection_established":
            return
        if _is_connection_bootstrap(event, payload):
            return
        try:
            if active is None:
                if event.startswith("chat:") or event == "system:error":
                    raise GateFailureError(f"orphan_event:{event}")
                return
            active.accept(event, payload, time.perf_counter())
            if event == "chat:control" and payload.get("signal") == "conversation-end":
                terminal.set()
        except Exception as exc:
            asynchronous_failure.append(exc)
            terminal.set()

    @client.event
    async def disconnect() -> None:
        disconnected.append(time.time())
        terminal.set()

    await client.connect(args.url, transports=["websocket"], wait_timeout=15)
    started = time.perf_counter()
    conversation_id = str(uuid4())
    try:
        probe = _identity(conversation_id)
        active = TurnTracker(probe, time.perf_counter())
        await client.emit("chat:text", {
            **probe, "text": "[inspection] ping", "source": "text",
            "is_inspection": True, "is_acceptance": False,
        })
        await asyncio.sleep(args.probe_seconds)
        if active.events:
            raise GateFailureError("inspection_probe_leaked")
        writer.update(probe={"identity": probe, "contained": True})
        active = None

        for index in range(args.turns):
            if disconnected:
                raise GateFailureError("connection_dropped")
            identity = _identity(conversation_id)
            terminal.clear()
            active = TurnTracker(identity, time.perf_counter())
            prompt = PROMPTS[index % len(PROMPTS)]
            await client.emit("chat:text", {
                **identity, "text": prompt, "source": "text",
                "is_inspection": False, "is_acceptance": True,
            })
            try:
                await asyncio.wait_for(terminal.wait(), timeout=args.turn_timeout)
            except TimeoutError as exc:
                raise GateFailureError(f"turn_timeout:{identity['task_id']}") from exc
            if asynchronous_failure:
                raise asynchronous_failure[0]
            turn = active.finalize()
            turn["input_index"] = index
            trace = await _get_json(f"{args.url}/api/stats/traces/{identity['task_id']}")
            if trace.get("trace_id", identity["task_id"]) != identity["task_id"]:
                raise GateFailureError("trace_identity_mismatch")
            turn["trace"] = trace
            if _contains_mock(trace):
                raise GateFailureError("mock_provider_in_trace")
            writer.append_turn(turn)
            active = None
            scheduled = started + ((index + 1) * args.duration / args.turns)
            await asyncio.sleep(max(0.0, scheduled - time.perf_counter()))

        elapsed = time.perf_counter() - started
        if elapsed < args.duration:
            await asyncio.sleep(args.duration - elapsed)
        elapsed = time.perf_counter() - started
        turns = writer.data["turns"]
        degradation_ok, degradation_reason = evaluate_degradation_budget(turns)
        text_p95 = percentile([turn["text_ready_ms"] for turn in turns], 95)
        media_p95 = percentile([
            turn["media_ready_ms"] for turn in turns if not turn["degraded"]
        ], 95)
        decisions = {
            "duration": elapsed >= args.duration,
            "turn_count": len(turns) >= args.turns,
            "disconnects": not disconnected,
            "text_p95": text_p95 <= 8000,
            "media_p95": media_p95 <= 20000,
            "degradation_budget": degradation_ok,
            "degradation_reason": degradation_reason,
        }
        if args.log_file:
            violations = scan_sanitized_logs(Path(args.log_file).read_text(
                encoding="utf-8", errors="replace"
            ))
            decisions["log_scan"] = not violations
            writer.update(log_scan={"path": args.log_file, "violations": violations})
        writer.update(
            duration_seconds=elapsed,
            thresholds={"text_ready_p95_ms": text_p95, "media_ready_p95_ms": media_p95},
            decisions=decisions,
        )
        if not all(value for value in decisions.values() if isinstance(value, bool)):
            raise GateFailureError("acceptance_threshold_failed")
    finally:
        if client.connected:
            await client.disconnect()


def _identity(conversation_id: str) -> dict[str, str]:
    task_id = str(uuid4())
    return {
        "message_id": str(uuid4()), "conversation_id": conversation_id,
        "task_id": task_id, "turn_id": task_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost")
    parser.add_argument("--duration", type=float, default=600.0)
    parser.add_argument("--turns", type=int, default=12)
    parser.add_argument("--turn-timeout", type=float, default=60.0)
    parser.add_argument("--probe-seconds", type=float, default=5.0)
    parser.add_argument("--log-file")
    parser.add_argument("--evidence-dir", default="evidence/golden-soak")
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = Path(args.evidence_dir) / f"golden-soak-{stamp}.json"
    writer = EvidenceWriter(path, {
        "status": "running", "turns": [],
        "environment": {
            "url": args.url, "platform": platform.platform(), "python": platform.python_version(),
            "revision": _revision(), "gpu": os.getenv("NVIDIA_VISIBLE_DEVICES", "unknown"),
            "duration_required": args.duration, "turns_required": args.turns,
        },
    })
    try:
        asyncio.run(run(args, writer))
    except Exception as exc:
        writer.update(status="failed", failure={"type": type(exc).__name__, "reason": str(exc)})
        print(path)
        return 1
    writer.update(status="passed")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
