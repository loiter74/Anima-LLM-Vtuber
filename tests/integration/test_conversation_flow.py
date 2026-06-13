"""Integration: conversation pipeline — server start → connect → text → pipeline runs."""

import asyncio, subprocess, sys, time, socketio, pytest

PORT, URL = 12394, "http://localhost:12394"

@pytest.fixture(scope="session")
def server():
    p = subprocess.Popen([sys.executable, "-m", "animetta.core.socketio_server"],
        env={**__import__("os").environ, "PYTHONPATH": "src"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    t0 = time.time()
    while time.time() - t0 < 30:
        if "Application startup complete" in (p.stdout.readline() or ""): break
    time.sleep(8)
    yield p
    p.terminate()
    try: p.wait(timeout=5)
    except subprocess.TimeoutExpired: p.kill()

class TestConversation:
    @pytest.mark.asyncio
    async def test_pipeline(self, server):
        sio, ev = socketio.AsyncClient(), {}
        @sio.on("*")
        async def _(e, d=None): ev.setdefault(e, []).append(d)
        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit("text_input", {"text": "Hello!", "user_id": "t", "from_name": "T"})
        await asyncio.sleep(30)
        await sio.disconnect()
        has_text = any(isinstance(d,dict) and d.get("text") for d in ev.get("chat:sentence",[]))
        has_expr = any(isinstance(d,dict) and d.get("emotion") for d in ev.get("chat:expression",[]))
        has_motion = any(isinstance(d,dict) and d.get("index",-1)>=0 for d in ev.get("chat:live2d_action",[]))
        errs = ev.get("error",[])
        expr_em = ev["chat:expression"][0].get("emotion","") if ev.get("chat:expression") else ""
        mot_idx = ev["chat:live2d_action"][0].get("index",-1) if ev.get("chat:live2d_action") else -1
        print(f"Events: {sorted(ev.keys())} | sentence={has_text} emotion={expr_em} motion={mot_idx} errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert len(ev) >= 2, "pipeline runs (≥2 event types)"
        assert not errs, f"errors: {errs}"
