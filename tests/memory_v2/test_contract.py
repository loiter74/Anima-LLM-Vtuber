from __future__ import annotations

import pytest

from animetta.memory.v2.context import MemoryContext
from animetta.memory.v2.system import LivingMemorySystem


@pytest.mark.asyncio
async def test_canonical_memory_contract_and_revisioned_mutations() -> None:
    system = LivingMemorySystem(db_path=":memory:")
    await system.initialize()
    context = MemoryContext(
        actor_id="bilibili:42",
        stream_id="bilibili:100",
        channel="bilibili",
        connection_id="socket-a",
    )
    atom = await system.encode(
        "我喜欢拿铁",
        "记住了。",
        context=context,
    )

    listing = await system.list_memories(limit=10)
    assert listing["revision"] >= 1
    assert listing["next_cursor"] is None
    assert len(listing["items"]) == 1
    dto = listing["items"][0]
    assert dto["id"] == atom.id
    assert dto["scope"] == "viewer"
    assert dto["subject_ids"] == ["bilibili:42"]
    assert dto["origin"]["connection_id"] == "socket-a"
    assert "session_id" not in dto
    assert isinstance(dto["confidence"], float)
    assert isinstance(dto["salience"], float)
    assert dto["relations"] == []

    searched = await system.search_memories("拿铁", limit=10)
    assert searched["items"][0]["id"] == atom.id

    pinned = await system.pin_memory(atom.id, pinned=True)
    assert pinned is not None
    assert pinned["retention_policy"] == "pinned"

    changed = await system.change_memory(atom.id, summary="观众偏好拿铁")
    assert changed is not None
    assert changed["summary"] == "观众偏好拿铁"
    assert changed["content"] == atom.content
    assert changed["version"] == 2

    forgotten = await system.forget_memory(atom.id)
    assert forgotten is not None
    assert forgotten["is_archived"] is True
    await system.shutdown()


@pytest.mark.asyncio
async def test_contract_rejects_invalid_cursor_and_blank_change() -> None:
    system = LivingMemorySystem(db_path=":memory:")
    await system.initialize()
    with pytest.raises(ValueError, match="cursor"):
        await system.list_memories(cursor="not-a-number")
    with pytest.raises(ValueError, match="summary"):
        await system.change_memory("missing", summary="")
    await system.shutdown()
