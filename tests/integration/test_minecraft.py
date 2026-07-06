"""Integration: Minecraft bot startup - verifies bot initializes without crash."""

import asyncio

import pytest
import socketio

PORT, URL = 12394, "http://localhost:12394"


class TestMinecraft:
    @pytest.mark.asyncio
    async def test_minecraft_bot_starts(self, server):
        """Verify minecraft bot initialization doesn't crash the server."""
        sio, ev = socketio.AsyncClient(), {}

        @sio.on("*")
        async def _(e, d=None):
            ev.setdefault(e, []).append(d)

        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await asyncio.sleep(15)
        await sio.disconnect()
        errs = ev.get("system:error", [])
        print(f"errors={errs}")
        assert "system:connection_established" in ev, "connect"
        assert not errs, f"errors: {errs}"
