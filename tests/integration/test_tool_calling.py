"""Integration: tool calling - calculator + get_current_time."""

import asyncio

import pytest
import socketio

PORT, URL = 12394, "http://localhost:12394"


class TestTools:
    @pytest.mark.asyncio
    async def test_calculator(self, server):
        sio, ev = socketio.AsyncClient(), {}

        @sio.on("*")
        async def _(e, d=None):
            ev.setdefault(e, []).append(d)

        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit(
            "chat:text",
            {
                "text": "What is 123+456? Use calculator.",
                "user_id": "c",
                "from_name": "C",
            },
        )
        await asyncio.sleep(30)
        await sio.disconnect()
        txt = " ".join(
            d.get("text", "") for d in ev.get("chat:sentence", []) if isinstance(d, dict)
        )
        errs = ev.get("system:error", [])
        print(f"response={txt[:200]} errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert not errs, f"errors: {errs}"

    @pytest.mark.asyncio
    async def test_time(self, server):
        sio, ev = socketio.AsyncClient(), {}

        @sio.on("*")
        async def _(e, d=None):
            ev.setdefault(e, []).append(d)

        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit(
            "chat:text",
            {
                "text": "What time is it? Use get_current_time.",
                "user_id": "t",
                "from_name": "T",
            },
        )
        await asyncio.sleep(30)
        await sio.disconnect()
        txt = " ".join(
            d.get("text", "") for d in ev.get("chat:sentence", []) if isinstance(d, dict)
        )
        errs = ev.get("system:error", [])
        print(f"response={txt[:200]} errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert not errs, f"errors: {errs}"
