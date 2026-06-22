"""Integration: subtitle/translation pipeline."""

import asyncio

import pytest
import socketio

PORT, URL = 12394, "http://localhost:12394"


class TestTranslation:
    @pytest.mark.asyncio
    async def test_translation_pipeline(self, server):
        sio, ev = socketio.AsyncClient(), {}

        @sio.on("*")
        async def _(e, d=None):
            ev.setdefault(e, []).append(d)

        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit(
            "text_input",
            {"text": "Hello! How are you?", "user_id": "tr", "from_name": "TR"},
        )
        await asyncio.sleep(30)
        await sio.disconnect()
        subs = ev.get("subtitle.translation", [])
        errs = ev.get("error", [])
        print(f"subtitle_events={len(subs)} errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert not errs, f"errors: {errs}"
