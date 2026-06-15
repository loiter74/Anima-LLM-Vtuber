"""Integration: subtitle/translation pipeline."""

import asyncio
import subprocess
import sys
import time

import pytest
import socketio

PORT, URL = 12394, "http://localhost:12394"

@pytest.fixture(scope="session")
def server():
    p = subprocess.Popen([sys.executable, "-m", "animetta.core.socketio_server"],
        env={**__import__("os").environ, "PYTHONPATH": "src"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    t0 = time.time()
    while time.time() - t0 < 30:
        if "Application startup complete" in (p.stdout.readline() or ""):
            break
    time.sleep(8)
    yield p
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()


class TestTranslation:
    @pytest.mark.asyncio
    async def test_translation_pipeline(self, server):
        sio, ev = socketio.AsyncClient(), {}
        @sio.on("*")
        async def _(e, d=None): ev.setdefault(e, []).append(d)
        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit("text_input", {"text": "Hello! How are you?", "user_id": "tr", "from_name": "TR"})
        await asyncio.sleep(30)
        await sio.disconnect()
        subs = ev.get("subtitle.translation", [])
        errs = ev.get("error", [])
        print(f"subtitle_events={len(subs)} errors={errs}")
        assert "connection-established" in ev, "connect"
        assert not errs, f"errors: {errs}"
