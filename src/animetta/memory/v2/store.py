"""AtomStore — unified persistence layer for MemoryAtoms.

SQLite for structured data + FTS5 for full-text search.
Chroma for vector semantic search.
Wiki export layer for human-readable backups.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import Any

from animetta.memory.v2.atom import (
    Layer,
    MemoryAtom,
    MemoryScope,
    MemoryVisibility,
    Relation,
)

logger = logging.getLogger(__name__)

# Optional Chroma support
try:
    import chromadb
    from chromadb.core.config import Settings

    _HAS_CHROMA = True
except ImportError:
    _HAS_CHROMA = False
    chromadb = None  # type: ignore[assignment]


class AtomStore:
    """Unified persistence for MemoryAtoms.

    Replaces MemoryEntryStore + WikiManager with a single store.
    Reuses existing SQLite patterns from storage/sqlite.py.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        db_path: str = "memory_db/living_memory.sqlite",
        *,
        enable_chroma: bool = True,
    ):
        self.db_path = db_path
        self.enable_chroma = enable_chroma
        self._conn: sqlite3.Connection | None = None
        self._chroma_client: Any = None
        self._chroma_collection: Any = None
        self._index_degraded = False
        self._index_last_error = ""

    async def initialize(self) -> None:
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        legacy_schema = self._is_legacy_schema()
        self._create_tables()
        self._migrate_schema(legacy_schema=legacy_schema)
        self._init_chroma()

    def _is_legacy_schema(self) -> bool:
        assert self._conn is not None
        exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_atoms'"
        ).fetchone()
        if not exists:
            return False
        columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(memory_atoms)").fetchall()
        }
        return "scope" not in columns

    def _init_chroma(self) -> None:
        """Initialize Chroma vector store if available."""
        if not self.enable_chroma or not _HAS_CHROMA:
            return
        try:
            self._chroma_client = chromadb.Client(
                Settings(
                    is_persistent=True,
                    persist_directory="memory_db/chroma_v2",
                    anonymized_telemetry=False,
                )
            )
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                name="memory_atoms_v2",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.warning(f"Chroma init failed, vector search disabled: {e}")
            self._chroma_client = None

    async def _vector_search(self, query_text: str, limit: int = 50) -> list[tuple[str, float]]:
        """Vector similarity search via Chroma. Returns [(atom_id, score), ...]."""
        if not self._chroma_collection:
            return []
        try:
            results = self._chroma_collection.query(
                query_texts=[query_text],
                n_results=limit,
                include=["distances"],
            )
            ids = results.get("ids", [[]])[0]
            distances = results.get("distances", [[]])[0]
            # Convert cosine distance to similarity score (1 - distance)
            return [(id_, 1.0 - float(dist)) for id_, dist in zip(ids, distances)]
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []

    async def _upsert_chroma(self, atom: MemoryAtom) -> None:
        """Add or update atom embedding in Chroma."""
        if not self._chroma_collection:
            return
        text = atom.summary or atom.content
        self._chroma_collection.upsert(
            ids=[atom.id],
            documents=[text],
            metadatas=[
                {
                    "layer": atom.layer.value,
                    "scope": atom.scope.value,
                    "confidence": atom.confidence,
                    "salience": atom.salience,
                }
            ],
        )

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memory_atoms (
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
                scope TEXT NOT NULL DEFAULT 'community',
                visibility TEXT NOT NULL DEFAULT 'internal',
                subject_ids TEXT NOT NULL DEFAULT '[]',
                origin TEXT NOT NULL DEFAULT '{}',
                trust_level REAL NOT NULL DEFAULT 0.5,
                retention_policy TEXT NOT NULL DEFAULT 'standard',
                index_state TEXT NOT NULL DEFAULT 'pending',
                decay_rate REAL DEFAULT 0.1,
                forget_at TEXT,
                is_archived INTEGER DEFAULT 0
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content, summary
            );

            CREATE TABLE IF NOT EXISTS memory_relations (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                PRIMARY KEY (source_id, target_id, relation_type)
            );

            CREATE TABLE IF NOT EXISTS memory_versions (
                atom_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                rewritten_at TEXT NOT NULL,
                emotion_valence REAL,
                emotion_arousal REAL,
                emotion_dominance REAL,
                PRIMARY KEY (atom_id, version)
            );

            CREATE TABLE IF NOT EXISTS memory_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_index_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                atom_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                revision INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

    def _migrate_schema(self, *, legacy_schema: bool) -> None:
        """Apply additive migrations and preserve all legacy atom data."""

        assert self._conn is not None
        columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(memory_atoms)").fetchall()
        }
        additions = {
            "scope": "TEXT NOT NULL DEFAULT 'community'",
            "visibility": "TEXT NOT NULL DEFAULT 'internal'",
            "subject_ids": "TEXT NOT NULL DEFAULT '[]'",
            "origin": "TEXT NOT NULL DEFAULT '{}'",
            "trust_level": "REAL NOT NULL DEFAULT 0.5",
            "retention_policy": "TEXT NOT NULL DEFAULT 'standard'",
            "index_state": "TEXT NOT NULL DEFAULT 'pending'",
        }
        for name, declaration in additions.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE memory_atoms ADD COLUMN {name} {declaration}")

        if legacy_schema:
            self._conn.execute(
                "UPDATE memory_atoms SET origin = ? WHERE origin = '{}'",
                (json.dumps({"legacy": True}),),
            )
            # A legacy database may not have populated the newly-created FTS table.
            self._conn.execute("DELETE FROM memory_fts")
            self._conn.execute(
                "INSERT INTO memory_fts(rowid, content, summary) "
                "SELECT rowid, content, COALESCE(summary, '') FROM memory_atoms"
            )

        self._conn.execute(
            "INSERT OR IGNORE INTO memory_metadata(key, value) VALUES ('revision', '0')"
        )
        self._conn.execute(
            "INSERT INTO memory_metadata(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(self.SCHEMA_VERSION),),
        )
        self._conn.commit()

    async def get_schema_version(self) -> int:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM memory_metadata WHERE key='schema_version'"
        ).fetchone()
        return int(row["value"]) if row else 0

    async def get_revision(self) -> int:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM memory_metadata WHERE key='revision'"
        ).fetchone()
        return int(row["value"]) if row else 0

    def _next_revision(self) -> int:
        assert self._conn is not None
        current = self._conn.execute(
            "SELECT value FROM memory_metadata WHERE key='revision'"
        ).fetchone()
        revision = (int(current["value"]) if current else 0) + 1
        self._conn.execute(
            "INSERT INTO memory_metadata(key, value) VALUES ('revision', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(revision),),
        )
        return revision

    def _enqueue_index(self, atom_id: str, operation: str, revision: int) -> None:
        assert self._conn is not None
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO memory_index_outbox(
                atom_id, operation, revision, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?)
            """,
            (atom_id, operation, revision, now, now),
        )

    async def get_index_backlog(self) -> int:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM memory_index_outbox WHERE status='pending'"
        ).fetchone()
        return int(row["count"])

    def get_index_health(self) -> dict[str, object]:
        """Return synchronous derived-index health for probes and runtime status."""

        return {
            "degraded": self._index_degraded,
            "last_error": self._index_last_error,
        }

    async def process_index_outbox(self, limit: int = 100) -> dict[str, int]:
        """Apply pending vector-index updates and retain failures for retry."""

        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM memory_index_outbox WHERE status='pending' "
            "ORDER BY revision, id LIMIT ?",
            (limit,),
        ).fetchall()
        succeeded = 0
        failed = 0
        for row in rows:
            atom = await self.get(row["atom_id"])
            if atom is None:
                self._conn.execute(
                    "UPDATE memory_index_outbox SET status='done', updated_at=? WHERE id=?",
                    (datetime.now(UTC).isoformat(), row["id"]),
                )
                succeeded += 1
                continue
            try:
                await self._upsert_chroma(atom)
            except Exception as exc:
                message = str(exc)
                self._conn.execute(
                    "UPDATE memory_index_outbox SET attempts=attempts+1, last_error=?, "
                    "updated_at=? WHERE id=?",
                    (message, datetime.now(UTC).isoformat(), row["id"]),
                )
                self._conn.execute(
                    "UPDATE memory_atoms SET index_state='pending' WHERE id=?",
                    (atom.id,),
                )
                self._index_degraded = True
                self._index_last_error = message
                logger.warning("Memory vector indexing failed for %s: %s", atom.id, message)
                failed += 1
            else:
                self._conn.execute(
                    "UPDATE memory_index_outbox SET status='done', last_error=NULL, "
                    "updated_at=? WHERE id=?",
                    (datetime.now(UTC).isoformat(), row["id"]),
                )
                self._conn.execute(
                    "UPDATE memory_atoms SET index_state='ready' WHERE id=?",
                    (atom.id,),
                )
                succeeded += 1

        self._conn.commit()
        if failed == 0 and await self.get_index_backlog() == 0:
            self._index_degraded = False
            self._index_last_error = ""
        return {"processed": len(rows), "succeeded": succeeded, "failed": failed}

    async def rebuild_indexes(self) -> int:
        """Rebuild FTS5 and Chroma from canonical active SQLite atoms."""

        assert self._conn is not None
        atoms = await self.get_all_active()
        self._conn.execute("DELETE FROM memory_fts")
        self._conn.execute(
            "INSERT INTO memory_fts(rowid, content, summary) "
            "SELECT rowid, content, COALESCE(summary, '') "
            "FROM memory_atoms WHERE is_archived=0"
        )

        failures: list[str] = []
        for atom in atoms:
            try:
                await self._upsert_chroma(atom)
            except Exception as exc:
                failures.append(f"{atom.id}: {exc}")
                self._conn.execute(
                    "UPDATE memory_atoms SET index_state='pending' WHERE id=?",
                    (atom.id,),
                )
            else:
                self._conn.execute(
                    "UPDATE memory_atoms SET index_state='ready' WHERE id=?",
                    (atom.id,),
                )

        if failures:
            self._index_degraded = True
            self._index_last_error = "; ".join(failures)
        else:
            self._conn.execute(
                "UPDATE memory_index_outbox SET status='done', last_error=NULL, "
                "updated_at=? WHERE status='pending'",
                (datetime.now(UTC).isoformat(),),
            )
            self._index_degraded = False
            self._index_last_error = ""
        self._conn.commit()
        return len(atoms)

    # ── CRUD ──

    async def create(self, atom: MemoryAtom) -> str:
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT INTO memory_atoms (id, layer, content, summary, occurred_at,
                rewritten_at, version, version_chain, confidence, salience,
                retrieval_count, last_accessed_at, emotion_valence, emotion_arousal,
                emotion_dominance, source_ids, relations, tags, scope, visibility,
                subject_ids, origin, trust_level, retention_policy, index_state,
                decay_rate, forget_at, is_archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                atom.id,
                atom.layer.value,
                atom.content,
                atom.summary,
                atom.occurred_at.isoformat(),
                atom.rewritten_at.isoformat()
                if atom.rewritten_at
                else atom.occurred_at.isoformat(),
                atom.version,
                json.dumps(atom.version_chain),
                atom.confidence,
                atom.salience,
                atom.retrieval_count,
                atom.last_accessed_at.isoformat() if atom.last_accessed_at else None,
                atom.emotion_valence,
                atom.emotion_arousal,
                atom.emotion_dominance,
                json.dumps(atom.source_ids),
                json.dumps([self._relation_to_dict(r) for r in atom.relations]),
                json.dumps(atom.tags),
                atom.scope.value,
                atom.visibility.value,
                json.dumps(atom.subject_ids),
                json.dumps(atom.origin),
                atom.trust_level,
                atom.retention_policy,
                atom.index_state,
                atom.decay_rate,
                atom.forget_at.isoformat() if atom.forget_at else None,
                1 if atom.is_archived else 0,
            ),
        )
        # Sync FTS5 index
        rowid = self._conn.execute(
            "SELECT rowid FROM memory_atoms WHERE id=?", (atom.id,)
        ).fetchone()[0]
        self._conn.execute(
            "INSERT INTO memory_fts(rowid, content, summary) VALUES (?, ?, ?)",
            (rowid, atom.content, atom.summary or ""),
        )
        revision = self._next_revision()
        self._enqueue_index(atom.id, "upsert", revision)
        self._conn.commit()
        return atom.id

    async def get(self, atom_id: str) -> MemoryAtom | None:
        assert self._conn is not None
        row = self._conn.execute("SELECT * FROM memory_atoms WHERE id = ?", (atom_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_atom(row)

    async def update(self, atom: MemoryAtom) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            UPDATE memory_atoms SET content=?, summary=?, rewritten_at=?,
                version=?, version_chain=?, confidence=?, salience=?,
                retrieval_count=?, last_accessed_at=?, emotion_valence=?,
                emotion_arousal=?, emotion_dominance=?, decay_rate=?,
                forget_at=?, is_archived=?, relations=?, tags=?, source_ids=?,
                scope=?, visibility=?, subject_ids=?, origin=?, trust_level=?,
                retention_policy=?, index_state=?
            WHERE id=?
        """,
            (
                atom.content,
                atom.summary,
                atom.rewritten_at.isoformat()
                if atom.rewritten_at
                else atom.occurred_at.isoformat(),
                atom.version,
                json.dumps(atom.version_chain),
                atom.confidence,
                atom.salience,
                atom.retrieval_count,
                atom.last_accessed_at.isoformat() if atom.last_accessed_at else None,
                atom.emotion_valence,
                atom.emotion_arousal,
                atom.emotion_dominance,
                atom.decay_rate,
                atom.forget_at.isoformat() if atom.forget_at else None,
                1 if atom.is_archived else 0,
                json.dumps([self._relation_to_dict(r) for r in atom.relations]),
                json.dumps(atom.tags),
                json.dumps(atom.source_ids),
                atom.scope.value,
                atom.visibility.value,
                json.dumps(atom.subject_ids),
                json.dumps(atom.origin),
                atom.trust_level,
                atom.retention_policy,
                atom.index_state,
                atom.id,
            ),
        )
        # Update FTS5 index
        self._conn.execute(
            "UPDATE memory_fts SET content=?, summary=? WHERE rowid=("
            "SELECT rowid FROM memory_atoms WHERE id=?)",
            (atom.content, atom.summary or "", atom.id),
        )
        revision = self._next_revision()
        self._enqueue_index(atom.id, "upsert", revision)
        self._conn.commit()

    async def create_version(
        self,
        atom_id: str,
        new_summary: str,
        new_confidence: float,
        new_emotion: tuple[float, float, float],
    ) -> MemoryAtom:
        """Create a new version after reconsolidation. Saves old version to history."""
        old = await self.get(atom_id)
        if old is None:
            raise ValueError(f"Atom {atom_id} not found")

        assert self._conn is not None

        # Save old version to history
        self._conn.execute(
            """
            INSERT OR REPLACE INTO memory_versions (atom_id, version, content, summary,
                rewritten_at, emotion_valence, emotion_arousal, emotion_dominance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                atom_id,
                old.version,
                old.content,
                old.summary,
                old.rewritten_at.isoformat() if old.rewritten_at else old.occurred_at.isoformat(),
                old.emotion_valence,
                old.emotion_arousal,
                old.emotion_dominance,
            ),
        )

        # Update with new version
        now = datetime.now(UTC)
        old.summary = new_summary
        old.confidence = new_confidence
        old.emotion_valence = new_emotion[0]
        old.emotion_arousal = new_emotion[1]
        old.emotion_dominance = new_emotion[2]
        old.version += 1
        old.version_chain = list(old.version_chain) + [atom_id]
        old.rewritten_at = now
        old.retrieval_count += 1
        old.last_accessed_at = now
        await self.update(old)
        return old

    async def get_all_active(self, limit: int = 1000) -> list[MemoryAtom]:
        """Get all non-archived atoms, ordered by salience descending."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM memory_atoms WHERE is_archived = 0 ORDER BY salience DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_atom(r) for r in rows]

    async def update_salience(self, atom_id: str, salience: float) -> None:
        assert self._conn is not None
        self._conn.execute(
            "UPDATE memory_atoms SET salience = ? WHERE id = ?",
            (salience, atom_id),
        )
        self._conn.commit()

    async def archive_below_threshold(self, threshold: float) -> int:
        """Archive all atoms with salience below threshold. Returns count."""
        assert self._conn is not None
        cursor = self._conn.execute(
            "UPDATE memory_atoms SET is_archived = 1 WHERE is_archived = 0 AND salience < ?",
            (threshold,),
        )
        self._conn.commit()
        return cursor.rowcount

    async def count_active(self) -> int:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM memory_atoms WHERE is_archived = 0"
        ).fetchone()
        return row["cnt"]

    async def search_fts(self, query: str, limit: int = 50) -> list[MemoryAtom]:
        """Full-text search via FTS5. Falls back to LIKE for CJK."""
        assert self._conn is not None
        # For CJK text — FTS5 can't tokenize, use LIKE instead
        if any("\u4e00" <= c <= "\u9fff" for c in query):
            rows = self._conn.execute(
                "SELECT * FROM memory_atoms WHERE (content LIKE ? OR summary LIKE ?) "
                "AND is_archived = 0 ORDER BY salience DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            return [self._row_to_atom(r) for r in rows]

        try:
            rows = self._conn.execute(
                "SELECT a.* FROM memory_atoms a "
                "JOIN memory_fts f ON a.rowid = f.rowid "
                "WHERE memory_fts MATCH ? AND a.is_archived = 0 "
                "ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except Exception:
            return []
        return [self._row_to_atom(r) for r in rows]

    async def hybrid_search(self, query: str, limit: int = 50) -> list[MemoryAtom]:
        """Hybrid search: vector (Chroma) + keyword (FTS5)."""
        results: dict[str, MemoryAtom] = {}
        scores: dict[str, float] = {}

        # Vector search
        vector_results = await self._vector_search(query, limit)
        for atom_id, score in vector_results:
            scores[atom_id] = scores.get(atom_id, 0) + 0.55 * score

        # Keyword search (FTS5)
        keyword_results = await self.search_fts(query, limit)
        for i, atom in enumerate(keyword_results):
            # BM25-like: higher rank = higher score
            kw_score = 1.0 / (1.0 + i)
            scores[atom.id] = scores.get(atom.id, 0) + 0.25 * kw_score
            results[atom.id] = atom

        # Fetch atoms not yet loaded (from vector search only)
        for atom_id in scores:
            if atom_id not in results:
                fetched = await self.get(atom_id)
                if fetched is not None and not fetched.is_archived:
                    results[atom_id] = fetched

        # Sort by combined score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [results[aid] for aid, _ in ranked if aid in results][:limit]

    # ── Serialization ──

    def _row_to_atom(self, row: sqlite3.Row) -> MemoryAtom:
        return MemoryAtom(
            id=row["id"],
            layer=Layer(row["layer"]),
            content=row["content"],
            summary=row["summary"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            rewritten_at=datetime.fromisoformat(row["rewritten_at"]),
            version=row["version"],
            version_chain=json.loads(row["version_chain"]),
            confidence=row["confidence"],
            salience=row["salience"],
            retrieval_count=row["retrieval_count"],
            last_accessed_at=(
                datetime.fromisoformat(row["last_accessed_at"]) if row["last_accessed_at"] else None
            ),
            emotion_valence=row["emotion_valence"],
            emotion_arousal=row["emotion_arousal"],
            emotion_dominance=row["emotion_dominance"],
            source_ids=json.loads(row["source_ids"]),
            relations=[self._dict_to_relation(d) for d in json.loads(row["relations"])],
            tags=json.loads(row["tags"]),
            scope=MemoryScope(row["scope"]),
            visibility=MemoryVisibility(row["visibility"]),
            subject_ids=json.loads(row["subject_ids"]),
            origin=json.loads(row["origin"]),
            trust_level=row["trust_level"],
            retention_policy=row["retention_policy"],
            index_state=row["index_state"],
            decay_rate=row["decay_rate"],
            forget_at=(datetime.fromisoformat(row["forget_at"]) if row["forget_at"] else None),
            is_archived=bool(row["is_archived"]),
        )

    @staticmethod
    def _relation_to_dict(r: Relation) -> dict:
        return {
            "source_id": r.source_id,
            "target_id": r.target_id,
            "relation_type": r.relation_type,
            "created_at": r.created_at.isoformat(),
            "metadata": r.metadata,
        }

    @staticmethod
    def _dict_to_relation(d: dict) -> Relation:
        return Relation(
            source_id=d["source_id"],
            target_id=d["target_id"],
            relation_type=d["relation_type"],
            created_at=datetime.fromisoformat(d["created_at"]),
            metadata=d.get("metadata", {}),
        )
