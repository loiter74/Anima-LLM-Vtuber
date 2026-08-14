#!/usr/bin/env python3
"""Run the production livestream continuity canary and write content-free evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen
from uuid import uuid4

import socketio

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from animetta.acceptance.conversation_continuity import (
    ContinuityStepEvidence,
    ContinuityStepId,
    build_sanitized_evidence,
)


class ContinuityCanaryError(RuntimeError):
    """The runtime failed a structural continuity assertion."""


@dataclass(frozen=True, slots=True)
class RuntimeTurn:
    trace_id: str
    response_text: str
    trace: Mapping[str, Any]


class CanaryBoundary(Protocol):
    async def readiness(self) -> Mapping[str, Any]: ...

    async def connect(self) -> str: ...

    async def disconnect(self) -> None: ...

    async def send_developer(self, text: str) -> RuntimeTurn: ...

    async def send_replay(
        self,
        text: str,
        *,
        is_probe: bool | None,
        expected_window_before: int,
    ) -> RuntimeTurn: ...


def _provider_is_real(readiness: Mapping[str, Any]) -> bool:
    components = readiness.get("components")
    llm = components.get("llm") if isinstance(components, Mapping) else None
    resolved = llm.get("resolved") if isinstance(llm, Mapping) else None
    identities = {
        str(resolved.get("type") or "").lower() if isinstance(resolved, Mapping) else "",
        str(resolved.get("provider") or "").lower() if isinstance(resolved, Mapping) else "",
    }
    return bool(
        readiness.get("ready") is True
        and readiness.get("profile") == "production"
        and readiness.get("acceptance_eligible") is True
        and isinstance(llm, Mapping)
        and llm.get("ready") is True
        and "mock" not in identities
        and any(identities)
    )


def _trace_step(
    step_id: ContinuityStepId,
    turn: RuntimeTurn,
    *,
    public_fact_recalled: bool | None = None,
    private_marker_absent: bool | None = None,
) -> ContinuityStepEvidence:
    attributes = turn.trace.get("attributes")
    if not isinstance(attributes, Mapping):
        attributes = {}
    required = {
        "conversation_scope_kind",
        "conversation_window_pairs_before",
        "conversation_window_pairs_after",
        "conversation_committed",
        "actor_role",
        "source",
    }
    missing = sorted(required - set(attributes))
    if missing:
        raise ContinuityCanaryError("trace_fields_missing:" + ",".join(missing))
    return ContinuityStepEvidence(
        step_id=step_id,
        trace_id=turn.trace_id,
        scope_kind=str(attributes["conversation_scope_kind"]),
        window_before=int(attributes["conversation_window_pairs_before"]),
        window_after=int(attributes["conversation_window_pairs_after"]),
        committed=attributes["conversation_committed"] is True,
        actor_role=str(attributes["actor_role"]),
        source=str(attributes["source"]),
        public_fact_recalled=public_fact_recalled,
        private_marker_absent=private_marker_absent,
    )


async def run_continuity_canary(
    boundary: CanaryBoundary,
    *,
    run_id: str | None = None,
    public_marker: str | None = None,
    private_marker: str | None = None,
    viewer_marker: str | None = None,
) -> dict[str, Any]:
    """Run the canonical scenario while retaining all content only in memory."""

    run_id = run_id or f"continuity-{uuid4().hex}"
    public_marker = public_marker or f"P-{uuid4().hex[:8]}"
    private_marker = private_marker or f"S-{uuid4().hex[:8]}"
    viewer_marker = viewer_marker or f"V-{uuid4().hex[:8]}"
    readiness = await boundary.readiness()
    provider_real = _provider_is_real(readiness)
    if not provider_real:
        raise ContinuityCanaryError("mock_or_unready_provider")

    steps: list[ContinuityStepEvidence] = []
    sid_a = await boundary.connect()
    seed = await boundary.send_developer(
        f"本场公开暗号是 {public_marker}；后台私密假标记是 {private_marker}"
    )
    steps.append(_trace_step(ContinuityStepId.DEVELOPER_SEED, seed))
    await boundary.disconnect()

    sid_b = await boundary.connect()
    socket_recreated = bool(sid_a and sid_b and sid_a != sid_b)
    probe = await boundary.send_replay(
        "默认重放探针",
        is_probe=None,
        expected_window_before=1,
    )
    steps.append(_trace_step(ContinuityStepId.REPLAY_PROBE, probe))

    viewer = await boundary.send_replay(
        f"问题标记 {viewer_marker}，请告诉我本场公开暗号",
        is_probe=False,
        expected_window_before=1,
    )
    steps.append(
        _trace_step(
            ContinuityStepId.VIEWER_REPLY,
            viewer,
            public_fact_recalled=public_marker in viewer.response_text,
            private_marker_absent=private_marker not in viewer.response_text,
        )
    )

    followup = await boundary.send_developer("上一条弹幕的问题标记是什么？")
    steps.append(
        _trace_step(
            ContinuityStepId.DEVELOPER_FOLLOWUP,
            followup,
            public_fact_recalled=viewer_marker in followup.response_text,
            private_marker_absent=private_marker not in followup.response_text,
        )
    )
    await boundary.disconnect()

    evidence = build_sanitized_evidence(
        run_id=run_id,
        provider_real=provider_real,
        socket_recreated=socket_recreated,
        steps=steps,
    )
    serialized = json.dumps(evidence, ensure_ascii=False)
    if any(marker in serialized for marker in (public_marker, private_marker, viewer_marker)):
        raise ContinuityCanaryError("evidence_content_leak")
    return evidence


class RuntimeCanaryBoundary:
    """Production Socket.IO and JSONL replay adapter."""

    def __init__(self, base_url: str, *, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.client: socketio.AsyncClient | None = None
        self._developer_pending: dict[str, dict[str, Any]] = {}
        self._bilibili_waiter: tuple[str, asyncio.Future[dict[str, Any]]] | None = None

    async def readiness(self) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._request_json, "GET", "/ready", None)

    async def connect(self) -> str:
        client = socketio.AsyncClient(reconnection=False)
        client.on("chat:sentence", self._on_sentence)
        client.on("chat:control", self._on_control)
        client.on("system:error", self._on_error)
        client.on("bilibili:danmaku_ai_reply", self._on_bilibili_reply)
        await client.connect(
            self.base_url.rstrip("/"),
            transports=["websocket", "polling"],
            wait_timeout=self.timeout_seconds,
        )
        self.client = client
        return str(client.sid or "")

    async def disconnect(self) -> None:
        client, self.client = self.client, None
        if client is not None and client.connected:
            await client.disconnect()

    async def send_developer(self, text: str) -> RuntimeTurn:
        if self.client is None or not self.client.connected:
            raise ContinuityCanaryError("socket_not_connected")
        task_id = str(uuid4())
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._developer_pending[task_id] = {"future": future, "chunks": []}
        payload = {
            "text": text,
            "message_id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "task_id": task_id,
            "turn_id": task_id,
        }
        await self.client.emit("chat:developer_text", payload)
        try:
            response = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        finally:
            self._developer_pending.pop(task_id, None)
        trace = await self._wait_trace(task_id)
        return RuntimeTurn(task_id, response, trace)

    async def send_replay(
        self,
        text: str,
        *,
        is_probe: bool | None,
        expected_window_before: int,
    ) -> RuntimeTurn:
        before_ids = await self._live_trace_ids()
        reply_future: asyncio.Future[dict[str, Any]] | None = None
        if is_probe is False:
            reply_future = asyncio.get_running_loop().create_future()
            self._bilibili_waiter = (text, reply_future)
        context: dict[str, Any] = {"room_id": 1, "memory_mode": "off"}
        if is_probe is not None:
            context["is_probe"] = is_probe
        jsonl = json.dumps(
            {
                "offset_ms": 0,
                "event_type": "danmaku",
                "actor_id": "continuity-canary",
                "text": text,
                "payload": {"program_context": context},
            },
            ensure_ascii=False,
        )
        await asyncio.to_thread(
            self._request_json,
            "POST",
            "/api/program-replays/start",
            {
                "source": "jsonl",
                "jsonl": jsonl,
                "room_id": 1,
                "creator_id": "continuity-canary",
                "speed": 100,
                "task_id": str(uuid4()),
            },
        )
        reply_payload: Mapping[str, Any] = {}
        if reply_future is not None:
            try:
                reply_payload = await asyncio.wait_for(
                    reply_future,
                    timeout=self.timeout_seconds,
                )
            finally:
                self._bilibili_waiter = None
        reply_id = str(reply_payload.get("reply_id") or "")
        trace_id, trace = await self._wait_unique_replay_trace(
            before_ids,
            expected_window_before=expected_window_before,
            preferred_trace_id=reply_id,
        )
        return RuntimeTurn(
            trace_id,
            str(reply_payload.get("reply_text") or ""),
            trace,
        )

    async def _on_sentence(self, payload: Mapping[str, Any]) -> None:
        task_id = str(payload.get("task_id") or "")
        pending = self._developer_pending.get(task_id)
        if pending is not None and payload.get("text"):
            pending["chunks"].append(str(payload["text"]))

    async def _on_control(self, payload: Mapping[str, Any]) -> None:
        if payload.get("signal") != "conversation-end":
            return
        task_id = str(payload.get("task_id") or "")
        pending = self._developer_pending.get(task_id)
        if pending is None:
            return
        future = pending["future"]
        if not future.done():
            future.set_result("".join(pending["chunks"]))

    async def _on_error(self, payload: Mapping[str, Any]) -> None:
        task_id = str(payload.get("task_id") or "")
        pending = self._developer_pending.get(task_id)
        if pending is None:
            return
        future = pending["future"]
        if not future.done():
            future.set_exception(ContinuityCanaryError("developer_turn_failed"))

    async def _on_bilibili_reply(self, payload: Mapping[str, Any]) -> None:
        waiter = self._bilibili_waiter
        if waiter is None or waiter[0] != str(payload.get("danmaku_text") or ""):
            return
        if not waiter[1].done():
            waiter[1].set_result(dict(payload))

    async def _live_trace_ids(self) -> set[str]:
        payload = await asyncio.to_thread(
            self._request_json,
            "GET",
            "/api/stats/live?limit=50",
            None,
        )
        turns = payload.get("turns")
        if not isinstance(turns, list):
            return set()
        return {
            str(turn.get("trace_id"))
            for turn in turns
            if isinstance(turn, Mapping) and turn.get("trace_id")
        }

    async def _wait_unique_replay_trace(
        self,
        before_ids: set[str],
        *,
        expected_window_before: int,
        preferred_trace_id: str,
    ) -> tuple[str, Mapping[str, Any]]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            candidates = (await self._live_trace_ids()) - before_ids
            if preferred_trace_id:
                candidates &= {preferred_trace_id}
            matches: list[tuple[str, Mapping[str, Any]]] = []
            for trace_id in candidates:
                try:
                    trace = await self._wait_trace(trace_id, attempts=1)
                except ContinuityCanaryError:
                    continue
                attributes = trace.get("attributes")
                if (
                    isinstance(attributes, Mapping)
                    and attributes.get("source") == "bilibili:danmaku"
                    and attributes.get("conversation_window_pairs_before") == expected_window_before
                ):
                    matches.append((trace_id, trace))
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ContinuityCanaryError("replay_trace_not_unique")
            await asyncio.sleep(0.25)
        raise ContinuityCanaryError("replay_trace_missing")

    async def _wait_trace(
        self,
        trace_id: str,
        *,
        attempts: int | None = None,
    ) -> Mapping[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        remaining = attempts
        while time.monotonic() < deadline and (remaining is None or remaining > 0):
            if remaining is not None:
                remaining -= 1
            try:
                trace = await asyncio.to_thread(
                    self._request_json,
                    "GET",
                    f"/api/stats/traces/{quote(trace_id, safe='')}",
                    None,
                )
            except ContinuityCanaryError:
                trace = {}
            attributes = trace.get("attributes")
            if (
                trace.get("finished_at") is not None
                and isinstance(attributes, Mapping)
                and "conversation_window_pairs_after" in attributes
            ):
                return trace
            await asyncio.sleep(0.25)
        raise ContinuityCanaryError("trace_incomplete")

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310 - caller supplies URL
                body = response.read().decode("utf-8", errors="replace")
        except (HTTPError, OSError, URLError) as exc:
            raise ContinuityCanaryError("runtime_http_failed") from exc
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ContinuityCanaryError("runtime_non_json") from exc
        if not isinstance(result, dict):
            raise ContinuityCanaryError("runtime_non_object")
        return result


def _failed_evidence(run_id: str, code: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "failed",
        "run_id": run_id,
        "provider_real": False,
        "socket_recreated": False,
        "steps": [],
        "error_codes": [code],
    }


def _safe_error_code(exc: BaseException) -> str:
    value = str(exc).strip()
    if value and all(
        character.islower() or character.isdigit() or character in "_:,-" for character in value
    ):
        return value[:160]
    return type(exc).__name__.lower()


async def _main(args: argparse.Namespace) -> int:
    run_id = f"continuity-{uuid4().hex}"
    boundary = RuntimeCanaryBoundary(args.url, timeout_seconds=args.turn_timeout)
    try:
        evidence = await run_continuity_canary(boundary, run_id=run_id)
    except (OSError, ValueError, ContinuityCanaryError) as exc:
        await boundary.disconnect()
        evidence = _failed_evidence(run_id, _safe_error_code(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if evidence["status"] == "passed" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "conversation-continuity" / "evidence.json",
    )
    parser.add_argument("--turn-timeout", type=float, default=120.0)
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
