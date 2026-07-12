from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from animetta.memory.v2.atom import Layer, MemoryAtom, MemoryScope, MemoryVisibility
from animetta.memory.v2.context import MemoryContext
from animetta.memory.v2.store import AtomStore


def test_memory_context_keeps_transport_identity_trace_only() -> None:
    context = MemoryContext(
        actor_id="bilibili:42",
        conversation_id="conversation-7",
        stream_id="stream-2026-07-12",
        persona_id="anima",
        channel="bilibili",
        connection_id="ephemeral-socket-sid",
    )

    assert context.actor_id == "bilibili:42"
    assert context.connection_id == "ephemeral-socket-sid"
    assert "ephemeral-socket-sid" not in context.visibility_keys()
    assert context.visibility_keys() == {
        "actor_id": "bilibili:42",
        "stream_id": "stream-2026-07-12",
    }


def test_memory_atom_has_safe_shared_defaults() -> None:
    atom = MemoryAtom(
        id="legacy-compatible",
        layer=Layer.RAW,
        content="hello",
        occurred_at=datetime.now(UTC),
    )

    assert atom.scope is MemoryScope.COMMUNITY
    assert atom.visibility is MemoryVisibility.INTERNAL
    assert atom.subject_ids == []
    assert atom.origin == {}
    assert atom.trust_level == pytest.approx(0.5)
    assert atom.retention_policy == "standard"
    assert atom.index_state == "pending"


@pytest.mark.asyncio
async def test_initialize_migrates_legacy_atoms_without_data_loss(tmp_path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE memory_atoms (
            id TEXT PRIMARY KEY,
            layer INTEGER NOT NULL,
            content TEXT NOT NULL,
            summary TEXT,
            occurred_at TEXT NOT NULL,
            rewritten_at TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            version_chain TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0.5,
            salience REAL DEFAULT 0.5,
            retrieval_count INTEGER DEFAULT 0,
            last_accessed_at TEXT,
            emotion_valence REAL DEFAULT 0.0,
            emotion_arousal REAL DEFAULT 0.0,
            emotion_dominance REAL DEFAULT 0.0,
            source_ids TEXT DEFAULT '[]',
            relations TEXT DEFAULT '[]',
            tags TEXT DEFAULT '[]',
            decay_rate REAL DEFAULT 0.1,
            forget_at TEXT,
            is_archived INTEGER DEFAULT 0
        );
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO memory_atoms (
            id, layer, content, summary, occurred_at, rewritten_at, tags
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("legacy-1", 0, "legacy content", "legacy summary", now, now, json.dumps(["old-sid"])),
    )
    conn.commit()
    conn.close()

    store = AtomStore(db_path=str(db_path), enable_chroma=False)
    await store.initialize()
    try:
        atom = await store.get("legacy-1")
        assert atom is not None
        assert atom.content == "legacy content"
        assert atom.tags == ["old-sid"]
        assert atom.scope is MemoryScope.COMMUNITY
        assert atom.visibility is MemoryVisibility.INTERNAL
        assert atom.origin == {"legacy": True}
        assert await store.get_schema_version() >= 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_create_persists_scope_and_advances_revision_outbox(tmp_path) -> None:
    store = AtomStore(db_path=str(tmp_path / "scoped.sqlite"), enable_chroma=False)
    await store.initialize()
    try:
        before = await store.get_revision()
        atom = MemoryAtom(
            id="viewer-1",
            layer=Layer.RAW,
            content="I like jasmine tea",
            occurred_at=datetime.now(UTC),
            scope=MemoryScope.VIEWER,
            visibility=MemoryVisibility.PRIVATE,
            subject_ids=["bilibili:42"],
            origin={"actor_id": "bilibili:42", "stream_id": "stream-1"},
            trust_level=0.8,
            retention_policy="long",
        )

        await store.create(atom)
        persisted = await store.get(atom.id)

        assert persisted is not None
        assert persisted.scope is MemoryScope.VIEWER
        assert persisted.visibility is MemoryVisibility.PRIVATE
        assert persisted.subject_ids == ["bilibili:42"]
        assert persisted.origin["stream_id"] == "stream-1"
        assert persisted.trust_level == pytest.approx(0.8)
        assert persisted.retention_policy == "long"
        assert await store.get_revision() == before + 1
        assert await store.get_index_backlog() == 1
    finally:
        await store.close()


class _FailingCollection:
    def upsert(self, **_kwargs) -> None:
        raise RuntimeError("vector index unavailable")


class _RecordingCollection:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def upsert(self, *, ids, **_kwargs) -> None:
        self.ids.extend(ids)


@pytest.mark.asyncio
async def test_index_outbox_retries_and_reports_degraded_health(tmp_path) -> None:
    store = AtomStore(db_path=str(tmp_path / "retry.sqlite"), enable_chroma=False)
    await store.initialize()
    try:
        await store.create(MemoryAtom(
            id="retry-1",
            layer=Layer.RAW,
            content="retry vector indexing",
            occurred_at=datetime.now(UTC),
        ))
        store._chroma_collection = _FailingCollection()

        first = await store.process_index_outbox()

        assert first == {"processed": 1, "succeeded": 0, "failed": 1}
        assert await store.get_index_backlog() == 1
        assert store.get_index_health()["degraded"] is True
        assert "vector index unavailable" in store.get_index_health()["last_error"]

        recording = _RecordingCollection()
        store._chroma_collection = recording
        second = await store.process_index_outbox()

        assert second == {"processed": 1, "succeeded": 1, "failed": 0}
        assert await store.get_index_backlog() == 0
        assert recording.ids == ["retry-1"]
        assert (await store.get("retry-1")).index_state == "ready"
        assert store.get_index_health()["degraded"] is False
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_rebuild_indexes_restores_fts_and_completes_outbox(tmp_path) -> None:
    store = AtomStore(db_path=str(tmp_path / "rebuild.sqlite"), enable_chroma=False)
    await store.initialize()
    try:
        await store.create(MemoryAtom(
            id="rebuild-1",
            layer=Layer.SEMANTIC,
            content="jasmine tea preference",
            occurred_at=datetime.now(UTC),
        ))
        assert store._conn is not None
        store._conn.execute("DELETE FROM memory_fts")
        store._conn.commit()
        assert await store.search_fts("jasmine") == []

        recording = _RecordingCollection()
        store._chroma_collection = recording
        rebuilt = await store.rebuild_indexes()

        assert rebuilt == 1
        assert [atom.id for atom in await store.search_fts("jasmine")] == ["rebuild-1"]
        assert recording.ids == ["rebuild-1"]
        assert await store.get_index_backlog() == 0
        assert store.get_index_health()["degraded"] is False
    finally:
        await store.close()
