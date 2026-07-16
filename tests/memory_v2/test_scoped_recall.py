from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from animetta.memory.v2.atom import Layer, MemoryAtom, MemoryScope, MemoryVisibility
from animetta.memory.v2.context import MemoryContext
from animetta.memory.v2.system import LivingMemorySystem


@pytest.fixture
async def memory_system():
    system = LivingMemorySystem(db_path=":memory:")
    system.store.enable_chroma = False
    await system.initialize()
    yield system
    await system.shutdown()


def _viewer(actor_id: str, connection_id: str) -> MemoryContext:
    return MemoryContext(
        actor_id=actor_id,
        conversation_id=f"conversation:{actor_id}",
        stream_id="stream:live-1",
        persona_id="anima",
        channel="bilibili",
        connection_id=connection_id,
    )


@pytest.mark.asyncio
async def test_same_viewer_recalls_after_socket_reconnect(memory_system) -> None:
    await memory_system.encode(
        user_input="我最喜欢茉莉花茶",
        agent_response="记住啦",
        context=_viewer("bilibili:42", "old-socket-sid"),
    )

    result = await memory_system.recall(
        "茉莉花茶",
        context=_viewer("bilibili:42", "new-socket-sid"),
    )

    assert [atom.scope for atom in result.atoms] == [MemoryScope.VIEWER]
    assert result.atoms[0].subject_ids == ["bilibili:42"]
    assert "old-socket-sid" not in result.atoms[0].tags


@pytest.mark.asyncio
async def test_viewer_private_memory_does_not_cross_actors(memory_system) -> None:
    await memory_system.encode(
        user_input="我住在杭州",
        agent_response="知道了",
        context=_viewer("bilibili:alice", "socket-a"),
    )

    result = await memory_system.recall(
        "杭州",
        context=_viewer("bilibili:bob", "socket-b"),
    )

    assert result.atoms == []


@pytest.mark.asyncio
async def test_community_memory_is_shared_across_viewers(memory_system) -> None:
    await memory_system.encode(
        user_input="今晚直播间都叫茉莉花茶月",
        agent_response="这个社区梗成立了",
        context=_viewer("bilibili:alice", "socket-a"),
        scope=MemoryScope.COMMUNITY,
        visibility=MemoryVisibility.PUBLIC,
    )

    result = await memory_system.recall(
        "茉莉花茶月",
        context=_viewer("bilibili:bob", "socket-b"),
    )

    assert len(result.atoms) == 1
    assert result.atoms[0].scope is MemoryScope.COMMUNITY


@pytest.mark.asyncio
async def test_anonymous_recall_excludes_viewer_private_memory(memory_system) -> None:
    await memory_system.encode(
        user_input="我的生日是七月十二日",
        agent_response="记住了",
        context=_viewer("bilibili:alice", "socket-a"),
    )
    await memory_system.encode(
        user_input="七月十二日是直播周年纪念日",
        agent_response="大家一起庆祝",
        context=_viewer("bilibili:alice", "socket-a"),
        scope=MemoryScope.COMMUNITY,
        visibility=MemoryVisibility.PUBLIC,
    )

    result = await memory_system.recall(
        "七月十二日",
        context=MemoryContext(channel="bilibili", connection_id="anonymous-sid"),
    )

    assert result.atoms
    assert all(atom.scope is not MemoryScope.VIEWER for atom in result.atoms)
    assert any(atom.scope is MemoryScope.COMMUNITY for atom in result.atoms)


@pytest.mark.asyncio
async def test_compilation_never_combines_different_viewer_subjects(memory_system) -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    atoms: list[MemoryAtom] = []
    for actor in ("bilibili:42", "bilibili:99"):
        for index in range(5):
            atom = MemoryAtom(
                id=f"raw-{actor}-{index}",
                layer=Layer.RAW,
                content=f"private fact {actor} {index}",
                occurred_at=old,
                scope=MemoryScope.VIEWER,
                visibility=MemoryVisibility.PRIVATE,
                subject_ids=[actor],
                origin={"actor_id": actor, "channel": "bilibili"},
            )
            await memory_system.store.create(atom)
            atoms.append(atom)

    await memory_system._try_compile(atoms)

    active = await memory_system.store.get_all_active()
    compiled = [atom for atom in active if atom.layer is Layer.EPISODIC]
    assert len(compiled) == 1
    assert compiled[0].scope is MemoryScope.VIEWER
    assert compiled[0].visibility is MemoryVisibility.PRIVATE
    assert compiled[0].subject_ids in (["bilibili:42"], ["bilibili:99"])
    source_subjects = {
        tuple(atom.subject_ids) for atom in atoms if atom.id in compiled[0].source_ids
    }
    assert len(source_subjects) == 1
