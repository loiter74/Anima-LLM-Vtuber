from __future__ import annotations

"""Tests for AtomStore SQLite persistence."""

from datetime import UTC, datetime

import pytest

from animetta.memory.v2.atom import Layer, MemoryAtom
from animetta.memory.v2.store import AtomStore


@pytest.fixture
async def store():
    s = AtomStore(db_path=":memory:")
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
class TestAtomStoreCRUD:
    async def test_create_and_get(self, store):
        atom = MemoryAtom(
            id="a1",
            layer=Layer.RAW,
            content="测试记忆",
            occurred_at=datetime.now(UTC),
            confidence=0.8,
        )
        created_id = await store.create(atom)
        assert created_id == "a1"

        retrieved = await store.get("a1")
        assert retrieved is not None
        assert retrieved.content == "测试记忆"
        assert retrieved.confidence == 0.8
        assert retrieved.layer == Layer.RAW

    async def test_get_nonexistent(self, store):
        result = await store.get("nonexistent")
        assert result is None

    async def test_update_atom(self, store):
        atom = MemoryAtom(
            id="a2",
            layer=Layer.RAW,
            content="原始内容",
            occurred_at=datetime.now(UTC),
        )
        await store.create(atom)

        atom.content = "更新内容"
        atom.confidence = 0.9
        await store.update(atom)

        retrieved = await store.get("a2")
        assert retrieved.content == "更新内容"
        assert retrieved.confidence == 0.9

    async def test_create_version_chain(self, store):
        atom = MemoryAtom(
            id="v1",
            layer=Layer.SEMANTIC,
            content="v1 内容",
            occurred_at=datetime.now(UTC),
        )
        await store.create(atom)

        new_atom = await store.create_version(
            atom_id="v1",
            new_summary="v2 摘要",
            new_confidence=0.85,
            new_emotion=(0.5, 0.3, 0.1),
        )
        assert new_atom.version == 2
        assert new_atom.summary == "v2 摘要"
        assert new_atom.retrieval_count >= 0

    async def test_get_all_active(self, store):
        a1 = MemoryAtom(
            id="act1",
            layer=Layer.RAW,
            content="active",
            occurred_at=datetime.now(UTC),
            salience=0.8,
        )
        a2 = MemoryAtom(
            id="act2",
            layer=Layer.RAW,
            content="archived",
            occurred_at=datetime.now(UTC),
            salience=0.5,
            is_archived=True,
        )
        await store.create(a1)
        await store.create(a2)

        active = await store.get_all_active()
        ids = {a.id for a in active}
        assert "act1" in ids
        assert "act2" not in ids  # archived

    async def test_count_active(self, store):
        await store.create(
            MemoryAtom(
                id="c1",
                layer=Layer.RAW,
                content="test",
                occurred_at=datetime.now(UTC),
            )
        )
        assert await store.count_active() >= 1

    async def test_archive_below_threshold(self, store):
        await store.create(
            MemoryAtom(
                id="low1",
                layer=Layer.RAW,
                content="low salience",
                occurred_at=datetime.now(UTC),
                salience=0.05,
            )
        )
        await store.create(
            MemoryAtom(
                id="high1",
                layer=Layer.RAW,
                content="high salience",
                occurred_at=datetime.now(UTC),
                salience=0.9,
            )
        )
        count = await store.archive_below_threshold(0.1)
        assert count >= 1

        low = await store.get("low1")
        assert low.is_archived is True
        high = await store.get("high1")
        assert high.is_archived is False


class TestAtomStoreEdgeCases:
    @pytest.mark.asyncio
    async def test_hybrid_search_empty_query(self, store):
        results = await store.hybrid_search("", 10)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_hybrid_search_cjk(self, store):
        atom = MemoryAtom(
            id="cjk", layer=Layer.RAW, content="我喜欢咖啡", occurred_at=datetime.now(UTC)
        )
        await store.create(atom)
        results = await store.hybrid_search("咖啡", 10)
        assert len(results) >= 0  # Should not error
