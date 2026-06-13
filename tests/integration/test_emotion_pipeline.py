"""Integration: emotion pipeline — expression + motion events."""

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

class TestEmotion:
    @pytest.mark.asyncio
    async def test_emotion(self, server):
        sio, ev = socketio.AsyncClient(), {}
        @sio.on("*")
        async def _(e, d=None): ev.setdefault(e, []).append(d)
        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit("text_input", {"text": "I am so happy today!", "user_id": "e", "from_name": "E"})
        await asyncio.sleep(30)
        await sio.disconnect()
        expr = ev.get("chat:expression",[])
        mot = ev.get("chat:live2d_action",[])
        errs = ev.get("error",[])
        em = expr[0].get("emotion","") if expr else ""
        mi = mot[0].get("index",-1) if mot else -1
        print(f"emotion={em} motion={mi} errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert not errs, f"errors: {errs}"
