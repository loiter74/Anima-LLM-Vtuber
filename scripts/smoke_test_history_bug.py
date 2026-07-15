#!/usr/bin/env python3
"""End-to-end smoke test for the "历史串台虫" (history bleed bug) fix.

Verifies the three-layer defense against a running Anima backend:

  Layer 1 — Inspection probes never reach the LLM.
  Layer 2 — Fallback/template replies are not persisted (validated by unit
            tests; this script confirms the LLM path still produces real
            Anima replies).
  Layer 3 — Real danmaku still flows through the full pipeline.

Usage:
    # Backend must be running on http://localhost first (Docker compose).
    python scripts/smoke_test_history_bug.py

    # Or point at a custom URL:
    ANIMA_BACKEND_URL=http://localhost:12394 python scripts/smoke_test_history_bug.py

Test matrix:
    A. Probe via is_inspection flag  -> expect NO sentence event (LLM skipped)
    B. Probe via [inspection] text    -> expect NO sentence event (text fallback)
    C. Real danmaku                   -> expect sentence + expression + audio
    D. Bare "ping" text               -> expect NO sentence event (token fallback)

Exit code:
    0 — all assertions passed
    1 — one or more assertions failed (see report)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from typing import Any

# ``socketio`` is a backend dev dependency; if missing, instruct the caller.
try:
    import socketio
except ImportError:  # pragma: no cover
    print("ERROR: python-socketio not installed. Run: pip install python-socketio[client]")
    sys.exit(2)


# ── Configuration ─────────────────────────────────────────────────────

DEFAULT_URL = os.environ.get("ANIMA_BACKEND_URL", "http://localhost")
# When running outside Docker, the backend speaks Socket.IO on its raw port.
# Inside Docker (nginx on :80), the same namespace is reverse-proxied.
if DEFAULT_URL == "http://localhost" and not os.environ.get("ANIMA_BACKEND_URL"):
    # Try the canonical manifest's configured backend port first.
    DEFAULT_URL = "http://localhost:12394"

CONNECT_TIMEOUT = 8.0          # seconds to establish connection
COLLECTION_WINDOW = 12.0       # seconds to collect events per test case
SETTLE_BETWEEN_TESTS = 1.5     # cool-down between cases

# Events that indicate the LLM pipeline ran (Layer 1 negative signal).
# Backend emits namespaced event names ("chat:sentence" etc., see
# config/socket-events.json). Use the namespaced forms here.
SENTENCE_EVENT = "chat:sentence"
EXPRESSION_EVENT = "chat:expression"
AUDIO_EVENT = "chat:audio_with_expression"
LLM_PIPELINE_EVENTS = {SENTENCE_EVENT, EXPRESSION_EVENT, AUDIO_EVENT}

# A real danmaku that should always reach the LLM in test C.
REAL_DANMAKU = "旅人，今天酒馆有什么推荐的吗？"


# ── Result bookkeeping ────────────────────────────────────────────────

class CaseResult:
    def __init__(self, name: str):
        self.name = name
        self.events: dict[str, list[dict]] = {}
        self.error: str | None = None
        self.duration_ms: float = 0.0

    def record(self, event: str, data: Any) -> None:
        self.events.setdefault(event, []).append(
            {"data": data, "t": time.time()}
        )

    @property
    def got_sentence(self) -> bool:
        return SENTENCE_EVENT in self.events and len(self.events[SENTENCE_EVENT]) > 0

    @property
    def got_full_pipeline(self) -> bool:
        return all(
            evt in self.events and self.events[evt]
            for evt in (SENTENCE_EVENT, EXPRESSION_EVENT, AUDIO_EVENT)
        )

    @property
    def first_sentence_text(self) -> str:
        evts = self.events.get(SENTENCE_EVENT, [])
        if not evts:
            return ""
        data = evts[0].get("data") or {}
        if isinstance(data, dict):
            return str(data.get("text", ""))[:80]
        return str(data)[:80]


# ── Harness ───────────────────────────────────────────────────────────

async def _connect(sio: socketio.AsyncClient, url: str) -> str | None:
    """Connect, returning None on success or an error message."""
    try:
        await asyncio.wait_for(
            sio.connect(url, transports=["websocket"]),
            timeout=CONNECT_TIMEOUT,
        )
        return None
    except Exception as exc:  # broad: timeout, refused, handshake error
        return f"connect failed: {exc!r}"


async def _run_case(
    url: str,
    name: str,
    payload: dict,
    *,
    expect_llm: bool,
) -> CaseResult:
    """Run one chat:text emission and collect events for COLLECTION_WINDOW."""
    result = CaseResult(name)
    sio = socketio.AsyncClient()

    @sio.on("*")
    async def catch_all(event: str, data: Any) -> None:  # noqa: ARG001
        result.record(event, data)

    start = time.perf_counter()

    err = await _connect(sio, url)
    if err:
        result.error = err
        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    try:
        await sio.emit("chat:text", payload)
        # Collect events for the full window.
        await asyncio.sleep(COLLECTION_WINDOW)
    except Exception as exc:
        result.error = f"during collection: {exc!r}"
    finally:
        with contextlib.suppress(Exception):
            await sio.disconnect()

    result.duration_ms = (time.perf_counter() - start) * 1000
    return result


# ── Individual test cases ────────────────────────────────────────────

async def test_a_inspection_flag_skipped(url: str) -> tuple[CaseResult, bool, str]:
    """A: is_inspection=True must NOT trigger the LLM pipeline."""
    res = await _run_case(
        url, "A_inspection_flag",
        {"text": "[inspection] ping", "mode": "text", "is_inspection": True},
        expect_llm=False,
    )
    if res.error:
        return res, False, f"infra error: {res.error}"
    ok = not res.got_sentence
    return res, ok, (
        "probe dropped before LLM (no sentence)"
        if ok else
        f"FAIL: probe reached LLM, got sentence: {res.first_sentence_text!r}"
    )


async def test_b_inspection_text_skipped(url: str) -> tuple[CaseResult, bool, str]:
    """B: [inspection] text without flag must still be dropped (text fallback)."""
    res = await _run_case(
        url, "B_inspection_text",
        {"text": "[inspection] ping", "mode": "text"},
        expect_llm=False,
    )
    if res.error:
        return res, False, f"infra error: {res.error}"
    ok = not res.got_sentence
    return res, ok, (
        "text-shaped probe dropped (no sentence)"
        if ok else
        f"FAIL: text probe reached LLM: {res.first_sentence_text!r}"
    )


async def test_c_real_danmaku_full_pipeline(url: str) -> tuple[CaseResult, bool, str]:
    """C: real danmaku must produce sentence + expression (+ audio if TTS real).

    The audio_with_expression event is only emitted when the configured TTS
    provider returns a real audio path. The default test config uses MockTTS
    which returns a non-existent path, so audio is OPTIONAL here. The hard
    requirements are: a sentence (LLM ran) and an expression (emotion node ran).
    """
    res = await _run_case(
        url, "C_real_danmaku",
        {"text": REAL_DANMAKU, "mode": "text"},
        expect_llm=True,
    )
    if res.error:
        return res, False, f"infra error: {res.error}"

    # Hard requirements: LLM + emotion ran.
    required = [SENTENCE_EVENT, EXPRESSION_EVENT]
    missing_hard = [e for e in required if e not in res.events or not res.events[e]]
    if missing_hard:
        return res, False, f"FAIL: missing required pipeline events: {sorted(missing_hard)}"

    # Sanity: the reply must not be a customer-service / fallback template.
    text = res.first_sentence_text
    bad_markers = ("有什么我可以帮助", "I need a moment to think", "我是一个 Mock LLM")
    for marker in bad_markers:
        if marker in text:
            return res, False, f"FAIL: reply is a template/fallback ({marker!r}): {text!r}"

    audio_ok = AUDIO_EVENT in res.events and bool(res.events[AUDIO_EVENT])
    audio_note = "+ audio" if audio_ok else "(audio skipped: MockTTS)"
    return res, True, f"full pipeline ok {audio_note}; reply={text!r}"


async def test_d_bare_ping_skipped(url: str) -> tuple[CaseResult, bool, str]:
    """D: bare 'ping' token must be dropped (token fallback in should_skip_llm)."""
    res = await _run_case(
        url, "D_bare_ping",
        {"text": "ping", "mode": "text"},
        expect_llm=False,
    )
    if res.error:
        return res, False, f"infra error: {res.error}"
    ok = not res.got_sentence
    return res, ok, (
        "bare 'ping' dropped (no sentence)"
        if ok else
        f"FAIL: 'ping' reached LLM: {res.first_sentence_text!r}"
    )


# ── Reporting ────────────────────────────────────────────────────────

def _format_result(name: str, res: CaseResult, ok: bool, detail: str) -> str:
    status = "PASS" if ok else "FAIL"
    event_summary = ", ".join(
        f"{e}×{len(v)}" for e, v in sorted(res.events.items())
    ) or "(none)"
    return (
        f"  [{status}] {name}  ({res.duration_ms:.0f} ms)\n"
        f"          {detail}\n"
        f"          events: {event_summary}"
    )


async def main() -> int:
    url = DEFAULT_URL
    print("═" * 70)
    print("历史串台虫 fix — end-to-end smoke test")
    print(f"Backend: {url}")
    print("═" * 70)

    cases = [
        test_a_inspection_flag_skipped,
        test_b_inspection_text_skipped,
        test_c_real_danmaku_full_pipeline,
        test_d_bare_ping_skipped,
    ]

    all_ok = True
    print("\nRunning 4 test cases (≈ 14s each)…\n")
    for case_fn in cases:
        # Each case uses its own connection, so they're independent.
        try:
            res, ok, detail = await case_fn(url)
        except Exception as exc:
            print(f"  [ERROR] {case_fn.__name__}: unhandled {exc!r}")
            all_ok = False
            await asyncio.sleep(SETTLE_BETWEEN_TESTS)
            continue
        print(_format_result(case_fn.__name__, res, ok, detail))
        if not ok:
            all_ok = False
        await asyncio.sleep(SETTLE_BETWEEN_TESTS)

    print("\n" + "═" * 70)
    print(f"RESULT: {'ALL PASS ✅' if all_ok else 'FAILURES ❌'}")
    print("═" * 70)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
