from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from animetta.memory.v2.context import MemoryContext
from animetta.memory.v2.system import LivingMemorySystem
from animetta.orchestration.server.handlers.memory_handlers import MemoryHandlers


@pytest.fixture
async def memory_handler():
    memory = LivingMemorySystem(db_path=":memory:")
    await memory.initialize()
    atom = await memory.encode(
        "我喜欢拿铁",
        "记住了",
        context=MemoryContext(actor_id="local:owner", channel="local"),
    )
    sio = SimpleNamespace(emit=AsyncMock())
    context = SimpleNamespace(memory_system=memory)
    base = SimpleNamespace(
        desktop_manager=None,
        live2d_manager=None,
        global_config=SimpleNamespace(),
        get_or_create_context=AsyncMock(return_value=context),
    )
    handler = MemoryHandlers(sio, SimpleNamespace(), base)
    yield handler, memory, atom, sio
    await memory.shutdown()


@pytest.mark.asyncio
async def test_typed_memory_acknowledgements_are_deterministic(memory_handler) -> None:
    handler, _, atom, _ = memory_handler

    listed = await handler.on_list("socket-a", {"limit": 20})
    assert listed["ok"] is True
    assert listed["data"]["items"][0]["id"] == atom.id
    assert "revision" in listed["data"]

    fetched = await handler.on_get("socket-a", {"id": atom.id})
    assert fetched["ok"] is True
    assert fetched["data"]["item"]["scope"] == "viewer"

    missing = await handler.on_get("socket-a", {"id": "missing"})
    assert missing == {
        "ok": False,
        "error": {"code": "NOT_FOUND", "message": "memory not found"},
    }
    invalid = await handler.on_search("socket-a", {"query": ""})
    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "INVALID_REQUEST"

    pinned = await handler.on_pin("socket-a", {"id": atom.id, "pinned": True})
    assert pinned["data"]["item"]["retention_policy"] == "pinned"
    changed = await handler.on_change(
        "socket-a", {"id": atom.id, "summary": "观众喜欢拿铁"}
    )
    assert changed["data"]["item"]["summary"] == "观众喜欢拿铁"
    forgotten = await handler.on_forget("socket-a", {"id": atom.id})
    assert forgotten["data"]["item"]["is_archived"] is True


@pytest.mark.asyncio
async def test_organize_job_events_are_scoped_by_job_id(memory_handler) -> None:
    handler, memory, _, sio = memory_handler
    memory.run_metabolism_tick = AsyncMock()

    accepted = await handler.on_memory_organize("socket-a", {})
    assert accepted["ok"] is True
    job_id = accepted["data"]["job_id"]
    await handler.wait_for_job(job_id)

    status = await handler.on_job("socket-a", {"job_id": job_id})
    assert status["ok"] is True
    assert status["data"]["status"] == "completed"
    job_payloads = [
        call.args[1]
        for call in sio.emit.await_args_list
        if call.args[0].startswith("memory:organize_")
    ]
    assert job_payloads
    assert {payload["job_id"] for payload in job_payloads} == {job_id}
