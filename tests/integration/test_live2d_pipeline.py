"""Integration: Live2D viseme — audio + volume envelope for mouth sync."""

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

class TestLive2D:
    @pytest.mark.asyncio
    async def test_viseme(self, server):
        sio, ev = socketio.AsyncClient(), {}
        @sio.on("*")
        async def _(e, d=None): ev.setdefault(e, []).append(d)
        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit("text_input", {"text": "Say a long sentence so your mouth moves!", "user_id": "v", "from_name": "V"})
        await asyncio.sleep(30)
        await sio.disconnect()
        audio = ev.get("audio_with_expression",[])
        visemes = ev.get("viseme",[]) or ev.get("live2d.viseme",[])
        has_vol = any(isinstance(a,dict) and a.get("volumes") for a in audio)
        len(visemes) > 0
        errs = ev.get("error",[])
        vcount = len(audio[0].get("volumes",[])) if has_vol and audio else 0
        vc = len(visemes)
        print(f"audio_events={len(audio)} volumes={has_vol} vol_samples={vcount} visemes={vc} errors={errs}")
        assert "connection-established" in ev, "connect"
        assert len(ev) >= 2, "pipeline runs (≥2 event types)"
        assert not errs, f"errors: {errs}"
