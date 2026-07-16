#!/usr/bin/env python3
"""
Multi-turn conversation smoke test for Animetta Docker deployment.

Usage:
    # Quick smoke (default: 3 rounds, 60s timeout)
    python tests/smoke/conversation_e2e.py

    # Custom params
    python tests/smoke/conversation_e2e.py --rounds 5 --timeout 90
    python tests/smoke/conversation_e2e.py --lang zh --rounds 10
    python tests/smoke/conversation_e2e.py --url http://my-ngrok.ngrok-free.dev
"""

import argparse
import asyncio
import sys
import time

import socketio

# ── Message pools ─────────────────────────────────────
MESSAGES_ZH = [
    "你好，今天心情怎么样？",
    "请用一句话介绍你自己。",
    "讲个冷笑话。",
    "谢谢，再见！",
]
MESSAGES_EN = [
    "Hello, how are you today?",
    "Tell me a short joke.",
    "What's your favorite color and why?",
    "Goodbye!",
]


def parse_args():
    p = argparse.ArgumentParser(description="Animetta conversation smoke test")
    p.add_argument(
        "--url", default="http://localhost:80", help="Backend URL (default: http://localhost:80)"
    )
    p.add_argument(
        "--rounds", type=int, default=3, help="Number of conversation rounds (default: 3)"
    )
    p.add_argument(
        "--timeout", type=int, default=60, help="Timeout per round in seconds (default: 60)"
    )
    p.add_argument(
        "--lang", choices=["zh", "en"], default="en", help="Message language (default: en)"
    )
    return p.parse_args()


def get_messages(pool, count):
    """Cycle through message pool if count > pool size."""
    return [pool[i % len(pool)] for i in range(count)]


async def main():
    args = parse_args()
    pool = MESSAGES_ZH if args.lang == "zh" else MESSAGES_EN
    messages = get_messages(pool, args.rounds)

    print(f"Animetta Smoke Test | {args.url} | {args.rounds}r | {args.lang} | {args.timeout}s")
    print("-" * 50)

    sio = socketio.AsyncClient()
    stats = {"connected": False, "sentences": 0, "audio": 0, "expressions": 0}
    complete = asyncio.Event()

    @sio.on("connect")
    def _connect():
        stats["connected"] = True
        print("[OK] Connected")

    @sio.on("connect_error")
    def _err(data):
        print(f"[FATAL] Connection error: {data}")
        sys.exit(1)

    @sio.on("chat:sentence")
    async def _sentence(data):
        stats["sentences"] += 1
        text = data.get("text", "")
        print(f"  [LLM] {text[:100]}")
        if data.get("is_complete"):
            complete.set()

    @sio.on("chat:audio_with_expression")
    def _audio(data):
        stats["audio"] += 1
        expr = data.get("chat:expression", "?")
        size = len(data.get("audio", b""))
        print(f"  [TTS] expr={expr} size={size}B")

    @sio.on("chat:expression")
    def _expr(data):
        stats["expressions"] += 1

    try:
        await sio.connect(args.url, socketio_path="/socket.io/", transports=["websocket"])
    except Exception as e:
        print(f"[FATAL] {e}")
        sys.exit(1)

    if not stats["connected"]:
        print("[FATAL] Not connected")
        sys.exit(1)

    t0 = time.time()
    for i, msg in enumerate(messages, 1):
        complete.clear()
        print(f"\n[{i}/{args.rounds}] >>> {msg}")
        await sio.emit("chat:text", {"text": msg})

        try:
            await asyncio.wait_for(complete.wait(), timeout=args.timeout)
        except TimeoutError:
            print(f"  [WARN] Timed out after {args.timeout}s")

    await sio.disconnect()
    elapsed = time.time() - t0

    ok = stats["connected"] and stats["sentences"] > 0
    print(f"\n{'─' * 50}")
    print(
        f"sentences={stats['sentences']} audio={stats['audio']} "
        f"expr={stats['expressions']} time={elapsed:.1f}s"
    )
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
