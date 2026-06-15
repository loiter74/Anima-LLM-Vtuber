"""Integration: ASR pipeline — audio input → speech recognition."""

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

class TestASR:
    @pytest.mark.asyncio
    async def test_asr(self, server):
        sio, ev = socketio.AsyncClient(), {}
        @sio.on("*")
        async def _(e, d=None): ev.setdefault(e, []).append(d)
        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit("raw_audio_data", {"audio": [], "sample_rate": 16000})
        await asyncio.sleep(10)
        await sio.disconnect()
        errs = ev.get("error",[])
        print(f"events={sorted(ev.keys())} errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert not errs, f"errors: {errs}"
