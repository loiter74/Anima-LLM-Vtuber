"""Integration: ASR pipeline — audio input → speech recognition."""

import asyncio

import pytest
import socketio

PORT, URL = 12394, "http://localhost:12394"

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
