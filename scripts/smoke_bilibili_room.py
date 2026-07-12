"""Opt-in real Bilibili room handshake smoke test.

Set BILIBILI_SMOKE_ROOM_ID to enable. This script only exercises the gateway
handshake; it never starts the AI reply pipeline.
"""

from __future__ import annotations

import os
import sys
import threading

from animetta.services.bilibili import DanmakuServiceGateway


def main() -> int:
    """Connect to one configured room and wait for a real status callback."""
    room_value = os.getenv("BILIBILI_SMOKE_ROOM_ID", "").strip()
    if not room_value:
        print("[SKIP] BILIBILI_SMOKE_ROOM_ID is not set")
        return 0
    try:
        room_id = int(room_value)
    except ValueError:
        print("[FAIL] BILIBILI_SMOKE_ROOM_ID must be an integer")
        return 2
    if room_id <= 0:
        print("[FAIL] BILIBILI_SMOKE_ROOM_ID must be positive")
        return 2

    timeout = float(os.getenv("BILIBILI_SMOKE_TIMEOUT_SECONDS", "30"))
    connected = threading.Event()
    failed = threading.Event()
    last_status = "No status callback"

    def on_status(is_connected: bool, message: str) -> None:
        nonlocal last_status
        last_status = message
        if is_connected:
            connected.set()
        elif "Max retries reached" in message:
            failed.set()

    def ignore_message(_message: object) -> None:
        return None

    gateway = DanmakuServiceGateway(
        room_id=room_id,
        sessdata=os.getenv("BILIBILI_SESSDATA", ""),
    )
    gateway.set_message_callback(ignore_message)
    gateway.set_status_callback(on_status)
    gateway.start()
    try:
        if connected.wait(timeout):
            print(f"[OK] Bilibili room {room_id} handshake succeeded")
            return 0
        if failed.is_set():
            print(f"[FAIL] Bilibili handshake failed: {last_status}")
        else:
            print(f"[FAIL] Bilibili handshake timed out: {last_status}")
        return 1
    finally:
        gateway.stop()


if __name__ == "__main__":
    sys.exit(main())
