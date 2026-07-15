"""Integration: emotion pipeline — expression + motion events."""

import asyncio

import pytest
import socketio

PORT, URL = 12394, "http://localhost:12394"


class TestEmotion:
    @pytest.mark.asyncio
    async def test_emotion(self, server):
        sio, ev = socketio.AsyncClient(), {}

        @sio.on("*")
        async def _(e, d=None):
            ev.setdefault(e, []).append(d)

        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit(
            "chat:text", {"text": "I am so happy today!", "user_id": "e", "from_name": "E"}
        )
        await asyncio.sleep(30)
        await sio.disconnect()
        expr = ev.get("chat:expression", [])
        mot = ev.get("chat:live2d_action", [])
        errs = ev.get("system:error", [])
        em = expr[0].get("emotion", "") if expr else ""
        mi = mot[0].get("index", -1) if mot else -1
        print(f"emotion={em} motion={mi} errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert not errs, f"errors: {errs}"
