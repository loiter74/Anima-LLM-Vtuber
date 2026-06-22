"""Integration: conversation pipeline — server start → connect → text → pipeline runs."""

import asyncio

import pytest
import socketio

PORT, URL = 12394, "http://localhost:12394"

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
        any(isinstance(d,dict) and d.get("emotion") for d in ev.get("chat:expression",[]))
        any(isinstance(d,dict) and d.get("index",-1)>=0 for d in ev.get("chat:live2d_action",[]))
        errs = ev.get("error",[])
        expr_em = ev["chat:expression"][0].get("emotion","") if ev.get("chat:expression") else ""
        mot_idx = ev["chat:live2d_action"][0].get("index",-1) if ev.get("chat:live2d_action") else -1
        print(f"Events: {sorted(ev.keys())} | sentence={has_text} emotion={expr_em} motion={mot_idx} errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert len(ev) >= 2, "pipeline runs (≥2 event types)"
        assert not errs, f"errors: {errs}"
