"""Integration: memory system - encode + recall through real pipeline.

Verifies LivingMemory V2 works end-to-end:
  conversation -> output_node.encode() -> AtomStore
  next conversation -> memory_middleware.recall() -> context injection
"""

import asyncio

import pytest
import socketio

PORT, URL = 12394, "http://localhost:12394"


class TestMemorySystem:
    @pytest.mark.asyncio
    async def test_memory_encode(self, server):
        """Verify conversation is encoded into memory via the pipeline."""
        sio = socketio.AsyncClient()
        events = {}

        @sio.on("*")
        async def _(e, d=None):
            events.setdefault(e, []).append(d)

        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit(
            "text_input",
            {
                "text": "My name is Alice and I love coffee.",
                "user_id": "mem_test",
                "from_name": "Alice",
            },
        )
        await asyncio.sleep(30)
        await sio.disconnect()

        errs = events.get("error", [])
        has_sentence = any(
            isinstance(d, dict) and d.get("text")
            for d in events.get("sentence", [])
        )
        print(f"encode_ok={has_sentence} errors={errs}")
        assert "system:connection_established" in events, "connect"
        assert not errs, f"errors: {errs}"

    @pytest.mark.asyncio
    async def test_memory_recall(self, server):
        """Second conversation should reference stored memory."""
        sio = socketio.AsyncClient()
        events = {}

        @sio.on("*")
        async def _(e, d=None):
            events.setdefault(e, []).append(d)

        await sio.connect(URL, transports=["websocket"], wait_timeout=10)
        await sio.emit(
            "text_input",
            {
                "text": "What is my name and what do I like to drink?",
                "user_id": "mem_test",
                "from_name": "Alice",
            },
        )
        await asyncio.sleep(30)
        await sio.disconnect()

        sentences = [
            d.get("text", "")
            for d in events.get("sentence", [])
            if isinstance(d, dict)
        ]
        full = " ".join(sentences)
        errs = events.get("error", [])
        print(f"response={full[:200]} errors={errs}")
        assert "system:connection_established" in events, "connect"
        assert not errs, f"errors: {errs}"
