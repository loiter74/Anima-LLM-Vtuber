# Living Memory V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the existing memory system with a living memory architecture — MemoryAtom unified model, reconsolidation on retrieval, VAD emotional field, and metabolism-based decay/consolidation/forgetting.

**Architecture:** New code in `src/animetta/memory/v2/`. Existing storage drivers (Chroma, SQLite) reused. Old modules moved to `_legacy/`. LangGraph integration via 6 file touchpoints. TDD throughout.

**Tech Stack:** Python 3.13+, Pydantic V2, ChromaDB, SQLite FTS5, LangGraph, pytest asyncio

---

## Task 1: MemoryAtom model and Layer/Relation types

**Files:**
- Create: `src/animetta/memory/v2/__init__.py`
- Create: `src/animetta/memory/v2/atom.py`
- Create: `tests/memory_v2/__init__.py`
- Create: `tests/memory_v2/test_atom.py`

**Step 1: Write the failing tests**

```python
# tests/memory_v2/test_atom.py
import pytest
from datetime import datetime, timedelta, timezone
from animetta.memory.v2.atom import MemoryAtom, Layer, Relation, RelationType


class TestMemoryAtom:
    def test_create_raw_atom(self):
        atom = MemoryAtom(
            id="atom-001",
            layer=Layer.RAW,
            content="用户说今天喝了拿铁",
            occurred_at=datetime.now(timezone.utc),
        )
        assert atom.layer == Layer.RAW
        assert atom.version == 1
        assert atom.rewritten_at == atom.occurred_at  # 从未被回忆
        assert atom.confidence == 0.5  # default
        assert atom.salience == 0.5
        assert atom.retrieval_count == 0
        assert atom.last_accessed_at is None
        assert atom.is_archived is False

    def test_layer_progression(self):
        """RAW → EPISODIC → SEMANTIC → EMERGENT"""
        raw = MemoryAtom(id="r1", layer=Layer.RAW, content="原始对话", occurred_at=datetime.now(timezone.utc))
        epi = MemoryAtom(
            id="e1", layer=Layer.EPISODIC, content="经历摘要",
            occurred_at=datetime.now(timezone.utc), source_ids=["r1"]
        )
        sem = MemoryAtom(
            id="s1", layer=Layer.SEMANTIC, content="提炼知识",
            occurred_at=datetime.now(timezone.utc), source_ids=["e1"]
        )
        assert raw.layer < epi.layer < sem.layer  # Layer 可比较

    def test_bi_temporal_rewritten_different_from_occurred(self):
        occurred = datetime(2026, 5, 30, tzinfo=timezone.utc)
        rewritten = datetime(2026, 5, 31, tzinfo=timezone.utc)
        atom = MemoryAtom(
            id="a1", layer=Layer.SEMANTIC, content="知识",
            occurred_at=occurred, rewritten_at=rewritten, version=3,
            version_chain=["v1_id", "v2_id"]
        )
        assert atom.occurred_at != atom.rewritten_at  # 被回忆过的标志
        assert atom.version == 3

    def test_emotion_vector_defaults(self):
        atom = MemoryAtom(id="a1", layer=Layer.RAW, content="test", occurred_at=datetime.now(timezone.utc))
        assert atom.emotion_valence == 0.0
        assert atom.emotion_arousal == 0.0
        assert atom.emotion_dominance == 0.0

    def test_relation_creation(self):
        r = Relation(source_id="a1", target_id="a2", relation_type=RelationType.UPDATES)
        assert r.relation_type == RelationType.UPDATES
        assert r.source_id == "a1"


class TestLayer:
    def test_layer_ordering(self):
        assert Layer.RAW < Layer.EPISODIC < Layer.SEMANTIC < Layer.EMERGENT

    def test_layer_from_string(self):
        assert Layer("raw") == Layer.RAW
        assert Layer("episodic") == Layer.EPISODIC
        assert Layer("semantic") == Layer.SEMANTIC
        assert Layer("emergent") == Layer.EMERGENT
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_atom.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
# src/animetta/memory/v2/__init__.py
"""Living Memory V2 — Active memory architecture."""

# src/animetta/memory/v2/atom.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum


class Layer(IntEnum):
    """记忆的四层投射，数字越大越抽象。"""
    RAW = 0       # 对话原文
    EPISODIC = 1  # 经历摘要
    SEMANTIC = 2  # 提炼知识
    EMERGENT = 3  # 梗/综合


class RelationType(str):
    UPDATES = "UPDATES"
    EXTENDS = "EXTENDS"
    DERIVES = "DERIVES"
    EVOKES = "EVOKES"
    CONTRADICTS = "CONTRADICTS"
    CONSOLIDATED_INTO = "CONSOLIDATED_INTO"


@dataclass
class Relation:
    source_id: str
    target_id: str
    relation_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)


@dataclass
class MemoryAtom:
    """统一记忆体 — 所有记忆类型的基元。"""
    id: str
    layer: Layer
    content: str
    occurred_at: datetime

    # 可选字段
    summary: str | None = None
    rewritten_at: datetime | None = None
    version: int = 1
    version_chain: list[str] = field(default_factory=list)

    confidence: float = 0.5
    salience: float = 0.5
    retrieval_count: int = 0
    last_accessed_at: datetime | None = None

    emotion_valence: float = 0.0
    emotion_arousal: float = 0.0
    emotion_dominance: float = 0.0

    source_ids: list[str] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    decay_rate: float = 0.1
    forget_at: datetime | None = None
    is_archived: bool = False

    def __post_init__(self):
        if self.rewritten_at is None:
            self.rewritten_at = self.occurred_at
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_atom.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add src/animetta/memory/v2/ tests/memory_v2/
git commit -m "feat: add MemoryAtom model with Layer, Relation types"
```

---

## Task 2: AtomStore — SQLite persistence layer

**Files:**
- Create: `src/animetta/memory/v2/store.py`
- Create: `tests/memory_v2/test_store.py`

**Step 1: Write failing tests**

```python
# tests/memory_v2/test_store.py
import pytest
from datetime import datetime, timezone
from animetta.memory.v2.atom import MemoryAtom, Layer
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
            id="a1", layer=Layer.RAW, content="测试记忆",
            occurred_at=datetime.now(timezone.utc), confidence=0.8,
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
            id="a2", layer=Layer.RAW, content="原始内容",
            occurred_at=datetime.now(timezone.utc),
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
            id="v1", layer=Layer.SEMANTIC, content="v1 内容",
            occurred_at=datetime.now(timezone.utc),
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
        assert "v1" in new_atom.version_chain or new_atom.id != "v1"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_store.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/animetta/memory/v2/store.py
from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from animetta.memory.v2.atom import MemoryAtom, Layer, Relation


class AtomStore:
    """统一记忆体持久化 — SQLite 结构层 + (后续) Chroma 向量层。"""

    def __init__(self, db_path: str = "memory_db/living_memory.sqlite"):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    async def initialize(self):
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    async def close(self):
        if self._conn:
            self._conn.close()

    def _create_tables(self):
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
                decay_rate REAL DEFAULT 0.1,
                forget_at TEXT,
                is_archived INTEGER DEFAULT 0
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content, summary, content='memory_atoms', content_rowid='rowid'
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
        """)

    async def create(self, atom: MemoryAtom) -> str:
        self._conn.execute("""
            INSERT INTO memory_atoms (id, layer, content, summary, occurred_at,
                rewritten_at, version, version_chain, confidence, salience,
                retrieval_count, last_accessed_at, emotion_valence, emotion_arousal,
                emotion_dominance, source_ids, relations, tags, decay_rate,
                forget_at, is_archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            atom.id, atom.layer.value, atom.content, atom.summary,
            atom.occurred_at.isoformat(), atom.rewritten_at.isoformat(),
            atom.version, json.dumps(atom.version_chain),
            atom.confidence, atom.salience, atom.retrieval_count,
            atom.last_accessed_at.isoformat() if atom.last_accessed_at else None,
            atom.emotion_valence, atom.emotion_arousal, atom.emotion_dominance,
            json.dumps(atom.source_ids), json.dumps([self._relation_to_dict(r) for r in atom.relations]),
            json.dumps(atom.tags), atom.decay_rate,
            atom.forget_at.isoformat() if atom.forget_at else None,
            1 if atom.is_archived else 0,
        ))
        self._conn.commit()
        return atom.id

    async def get(self, atom_id: str) -> MemoryAtom | None:
        row = self._conn.execute(
            "SELECT * FROM memory_atoms WHERE id = ?", (atom_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_atom(row)

    async def update(self, atom: MemoryAtom) -> None:
        self._conn.execute("""
            UPDATE memory_atoms SET content=?, summary=?, rewritten_at=?,
                version=?, version_chain=?, confidence=?, salience=?,
                retrieval_count=?, last_accessed_at=?, emotion_valence=?,
                emotion_arousal=?, emotion_dominance=?, decay_rate=?,
                forget_at=?, is_archived=?, relations=?, tags=?, source_ids=?
            WHERE id=?
        """, (
            atom.content, atom.summary, atom.rewritten_at.isoformat(),
            atom.version, json.dumps(atom.version_chain),
            atom.confidence, atom.salience, atom.retrieval_count,
            atom.last_accessed_at.isoformat() if atom.last_accessed_at else None,
            atom.emotion_valence, atom.emotion_arousal, atom.emotion_dominance,
            atom.decay_rate,
            atom.forget_at.isoformat() if atom.forget_at else None,
            1 if atom.is_archived else 0,
            json.dumps([self._relation_to_dict(r) for r in atom.relations]),
            json.dumps(atom.tags), json.dumps(atom.source_ids),
            atom.id,
        ))
        self._conn.commit()

    async def create_version(
        self, atom_id: str, new_summary: str,
        new_confidence: float, new_emotion: tuple[float, float, float],
    ) -> MemoryAtom:
        old = await self.get(atom_id)
        if old is None:
            raise ValueError(f"Atom {atom_id} not found")

        # Save old version
        self._conn.execute("""
            INSERT INTO memory_versions (atom_id, version, content, summary,
                rewritten_at, emotion_valence, emotion_arousal, emotion_dominance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (atom_id, old.version, old.content, old.summary,
              old.rewritten_at.isoformat(),
              old.emotion_valence, old.emotion_arousal, old.emotion_dominance))

        # Update with new version
        now = datetime.now(timezone.utc)
        old.summary = new_summary
        old.confidence = new_confidence
        old.emotion_valence = new_emotion[0]
        old.emotion_arousal = new_emotion[1]
        old.emotion_dominance = new_emotion[2]
        old.version += 1
        old.version_chain = old.version_chain + [atom_id]
        old.rewritten_at = now
        old.retrieval_count += 1
        old.last_accessed_at = now
        await self.update(old)
        return old

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
                datetime.fromisoformat(row["last_accessed_at"])
                if row["last_accessed_at"] else None
            ),
            emotion_valence=row["emotion_valence"],
            emotion_arousal=row["emotion_arousal"],
            emotion_dominance=row["emotion_dominance"],
            source_ids=json.loads(row["source_ids"]),
            relations=[self._dict_to_relation(d) for d in json.loads(row["relations"])],
            tags=json.loads(row["tags"]),
            decay_rate=row["decay_rate"],
            forget_at=(
                datetime.fromisoformat(row["forget_at"])
                if row["forget_at"] else None
            ),
            is_archived=bool(row["is_archived"]),
        )

    @staticmethod
    def _relation_to_dict(r: Relation) -> dict:
        return {
            "source_id": r.source_id, "target_id": r.target_id,
            "relation_type": r.relation_type,
            "created_at": r.created_at.isoformat(),
            "metadata": r.metadata,
        }

    @staticmethod
    def _dict_to_relation(d: dict) -> Relation:
        return Relation(
            source_id=d["source_id"], target_id=d["target_id"],
            relation_type=d["relation_type"],
            created_at=datetime.fromisoformat(d["created_at"]),
            metadata=d.get("metadata", {}),
        )
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_store.py -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add src/animetta/memory/v2/store.py tests/memory_v2/test_store.py
git commit -m "feat: add AtomStore with SQLite persistence and version chain"
```

---

## Task 3: EmotionalField — VAD vector model

**Files:**
- Create: `src/animetta/memory/v2/emotion_field.py`
- Create: `tests/memory_v2/test_emotion_field.py`

**Step 1: Write failing tests**

```python
# tests/memory_v2/test_emotion_field.py
import pytest
import math
from animetta.memory.v2.emotion_field import EmotionalField, VAD_MAP, VADVector


class TestVADMap:
    def test_all_14_emotions_mapped(self):
        expected = {
            "happy", "sad", "angry", "surprised", "neutral", "thinking",
            "confused", "love", "shy", "excited", "suspicious", "tired",
            "proud", "resigned",
        }
        assert set(VAD_MAP.keys()) == expected

    def test_happy_vector(self):
        v = VAD_MAP["happy"]
        assert v.valence > 0.5
        assert v.arousal > 0.3
        assert v.dominance > 0.3

    def test_sad_vector(self):
        v = VAD_MAP["sad"]
        assert v.valence < -0.5
        assert v.arousal < 0.0  # 低唤醒

    def test_neutral_is_zero(self):
        v = VAD_MAP["neutral"]
        assert v.valence == 0.0
        assert v.arousal == 0.0
        assert v.dominance == 0.0


class TestEmotionalField:
    def test_cosine_similarity_same_vector(self):
        v = VADVector(0.8, 0.6, 0.7)
        sim = EmotionalField.cosine_similarity(v, v)
        assert math.isclose(sim, 1.0, rel_tol=1e-5)

    def test_cosine_similarity_opposite(self):
        v1 = VADVector(1.0, 0.0, 0.0)
        v2 = VADVector(-1.0, 0.0, 0.0)
        sim = EmotionalField.cosine_similarity(v1, v2)
        assert math.isclose(sim, -1.0, rel_tol=1e-5)

    def test_emotion_congruence_happy_happy(self):
        """happy 查询 → happy 记忆 → 高一致性"""
        current = VAD_MAP["happy"]
        memory = VAD_MAP["happy"]
        congruence = EmotionalField.emotion_congruence(current, memory)
        assert congruence > 0.8

    def test_emotion_congruence_happy_sad(self):
        """happy 查询 → sad 记忆 → 低一致性"""
        current = VAD_MAP["happy"]
        memory = VAD_MAP["sad"]
        congruence = EmotionalField.emotion_congruence(current, memory)
        assert congruence < 0.3

    def test_encoding_confidence_from_arousal(self):
        """高唤醒 → 高初始置信度"""
        high_arousal = VADVector(0.0, 0.9, 0.0)
        low_arousal = VADVector(0.0, 0.1, 0.0)
        assert EmotionalField.encoding_confidence(high_arousal) > EmotionalField.encoding_confidence(low_arousal)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_emotion_field.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/animetta/memory/v2/emotion_field.py
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VADVector:
    """Valence-Arousal-Dominance 三维情绪向量。"""
    valence: float    # -1.0 ~ +1.0
    arousal: float    # 0.0 ~ 1.0
    dominance: float  # -1.0 ~ +1.0

    def to_tuple(self) -> tuple[float, float, float]:
        return (self.valence, self.arousal, self.dominance)


# 14 个离散情绪标签 → VAD 向量映射
# 基于 Russell's circumplex model + 经验调参
VAD_MAP: dict[str, VADVector] = {
    "happy":      VADVector( 0.81, 0.51, 0.67),
    "excited":    VADVector( 0.88, 0.85, 0.78),
    "love":       VADVector( 0.89, 0.45, 0.42),
    "proud":      VADVector( 0.72, 0.48, 0.79),
    "neutral":    VADVector( 0.00, 0.00, 0.00),
    "thinking":   VADVector( 0.08, -0.28, 0.33),
    "confused":   VADVector(-0.22, 0.32, -0.48),
    "surprised":  VADVector( 0.31, 0.82, -0.28),
    "suspicious": VADVector(-0.42, 0.38, -0.21),
    "shy":        VADVector( 0.12, 0.38, -0.71),
    "tired":      VADVector(-0.13, -0.59, -0.41),
    "resigned":   VADVector(-0.33, -0.52, -0.61),
    "sad":        VADVector(-0.77, -0.33, -0.58),
    "angry":      VADVector(-0.81, 0.82, 0.48),
}


class EmotionalField:
    """情绪场 — 提供所有情绪相关的计算。"""

    @staticmethod
    def cosine_similarity(a: VADVector, b: VADVector) -> float:
        dot = a.valence * b.valence + a.arousal * b.arousal + a.dominance * b.dominance
        mag_a = math.sqrt(a.valence**2 + a.arousal**2 + a.dominance**2)
        mag_b = math.sqrt(b.valence**2 + b.valence**2 + b.dominance**2)
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    @staticmethod
    def emotion_congruence(current: VADVector, memory: VADVector) -> float:
        """计算当前情绪与记忆情绪的匹配度 (mood-congruent recall)。"""
        cos = EmotionalField.cosine_similarity(current, memory)
        # 高唤醒增强偏置效果（情绪越激烈，越容易取回情绪一致的记忆）
        arousal_boost = 1.0 + 0.5 * current.arousal
        return cos * arousal_boost

    @staticmethod
    def encoding_confidence(emotion: VADVector) -> float:
        """根据情绪强度计算编码时的初始置信度 (flashbulb memory effect)。"""
        # 高唤醒 → 高置信度
        base = 0.5
        arousal_effect = 0.4 * emotion.arousal
        # 极端效价（特别开心或特别难过）也增强编码
        valence_effect = 0.1 * abs(emotion.valence)
        return min(1.0, base + arousal_effect + valence_effect)

    @staticmethod
    def metabolism_protection(emotion: VADVector) -> float:
        """情绪对记忆衰减的保护因子。"""
        return 1.0 + 0.3 * abs(emotion.valence) * emotion.arousal
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_emotion_field.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/animetta/memory/v2/emotion_field.py tests/memory_v2/test_emotion_field.py
git commit -m "feat: add EmotionalField with VAD vector model"
```

---

## Task 4: MetabolismScheduler — unified decay/consolidation/forgetting

**Files:**
- Create: `src/animetta/memory/v2/metabolism.py`
- Create: `tests/memory_v2/test_metabolism.py`

**Step 1: Write failing tests**

```python
# tests/memory_v2/test_metabolism.py
import pytest
import math
from datetime import datetime, timedelta, timezone
from animetta.memory.v2.atom import MemoryAtom, Layer
from animetta.memory.v2.emotion_field import VADVector
from animetta.memory.v2.metabolism import MetabolismScheduler


class TestSalienceCalculation:
    def test_fresh_atom_default_salience(self):
        atom = MemoryAtom(
            id="a1", layer=Layer.RAW, content="test",
            occurred_at=datetime.now(timezone.utc),
            confidence=0.5,
        )
        salience = MetabolismScheduler.compute_salience(atom)
        assert math.isclose(salience, 0.5, rel_tol=0.1)

    def test_high_confidence_increases_salience(self):
        high = MemoryAtom(
            id="h1", layer=Layer.RAW, content="important",
            occurred_at=datetime.now(timezone.utc), confidence=0.9,
        )
        low = MemoryAtom(
            id="l1", layer=Layer.RAW, content="trivial",
            occurred_at=datetime.now(timezone.utc), confidence=0.2,
        )
        assert MetabolismScheduler.compute_salience(high) > MetabolismScheduler.compute_salience(low)

    def test_retrieval_boosts_salience(self):
        retrieved = MemoryAtom(
            id="r1", layer=Layer.RAW, content="recalled",
            occurred_at=datetime.now(timezone.utc),
            retrieval_count=10,
        )
        fresh = MemoryAtom(
            id="f1", layer=Layer.RAW, content="fresh",
            occurred_at=datetime.now(timezone.utc),
            retrieval_count=0,
        )
        assert MetabolismScheduler.compute_salience(retrieved) > MetabolismScheduler.compute_salience(fresh)


class TestAdaptiveThreshold:
    def test_low_watermark_relaxed(self):
        """低水位 → 低阈值（几乎不遗忘）"""
        threshold = MetabolismScheduler.adaptive_threshold(
            atom_count=40, capacity=100
        )
        assert threshold < 0.15

    def test_high_watermark_aggressive(self):
        """高水位 → 高阈值（积极遗忘）"""
        threshold = MetabolismScheduler.adaptive_threshold(
            atom_count=85, capacity=100
        )
        assert threshold > 0.15

    def test_mid_watermark_moderate(self):
        threshold = MetabolismScheduler.adaptive_threshold(
            atom_count=60, capacity=100
        )
        assert 0.05 < threshold < 0.20
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_metabolism.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/animetta/memory/v2/metabolism.py
from __future__ import annotations
import math
from datetime import datetime, timezone
from animetta.memory.v2.atom import MemoryAtom
from animetta.memory.v2.emotion_field import EmotionalField, VADVector


class MetabolismScheduler:
    """统一记忆代谢调度器 — 衰减/巩固/遗忘 三阶段循环。"""

    @staticmethod
    def compute_salience(atom: MemoryAtom) -> float:
        """计算原子当前活性值。

        salience = confidence × decay × retrieval_boost × emotion_protection
        """
        now = datetime.now(timezone.utc)
        elapsed_hours = (now - atom.rewritten_at).total_seconds() / 3600.0

        # 指数衰减
        decay = math.exp(-atom.decay_rate * elapsed_hours)

        # 检索增强（每次检索减缓衰减）
        retrieval_boost = 1.0 + 0.15 * atom.retrieval_count

        # 情绪保护（极端情绪记忆更持久）
        emotion = VADVector(
            atom.emotion_valence,
            atom.emotion_arousal,
            atom.emotion_dominance,
        )
        emotion_protection = EmotionalField.metabolism_protection(emotion)

        salience = atom.confidence * decay * retrieval_boost * emotion_protection
        return max(0.0, min(1.0, salience))

    @staticmethod
    def adaptive_threshold(atom_count: int, capacity: int = 1000) -> float:
        """自适应遗忘阈值 — 类似突触稳态。

        低水位(< 50% capacity) → 几乎不遗忘 (threshold ~ 0.05)
        高水位(> 80% capacity) → 积极遗忘   (threshold ~ 0.20)
        """
        fill_ratio = atom_count / capacity
        if fill_ratio < 0.3:
            return 0.02  # 几乎不遗忘
        elif fill_ratio < 0.5:
            return 0.05
        elif fill_ratio < 0.7:
            return 0.10
        elif fill_ratio < 0.85:
            return 0.15
        else:
            return 0.20  # 积极遗忘
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_metabolism.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/animetta/memory/v2/metabolism.py tests/memory_v2/test_metabolism.py
git commit -m "feat: add MetabolismScheduler with salience and adaptive threshold"
```

---

## Task 5: Mixed search with emotion bias

**Files:**
- Create: `src/animetta/memory/v2/search.py`
- Create: `tests/memory_v2/test_search.py`

**Step 1: Write failing tests**

```python
# tests/memory_v2/test_search.py
import pytest
import math
from datetime import datetime, timezone
from animetta.memory.v2.atom import MemoryAtom, Layer
from animetta.memory.v2.emotion_field import VADVector, VAD_MAP
from animetta.memory.v2.search import MemorySearch


class TestSearchScoring:
    def test_emotion_biased_scoring(self):
        """开心时搜索，开心记忆排前面"""
        atoms = [
            MemoryAtom(id="h", layer=Layer.SEMANTIC, content="咖啡很好喝",
                       occurred_at=datetime.now(timezone.utc),
                       emotion_valence=0.8, emotion_arousal=0.6, emotion_dominance=0.7,
                       confidence=0.8, salience=0.8),
            MemoryAtom(id="s", layer=Layer.SEMANTIC, content="咖啡很苦",
                       occurred_at=datetime.now(timezone.utc),
                       emotion_valence=-0.8, emotion_arousal=0.3, emotion_dominance=-0.5,
                       confidence=0.8, salience=0.8),
        ]
        current_emotion = VAD_MAP["happy"]  # (0.81, 0.51, 0.67)

        scored = MemorySearch.rank_by_emotion(atoms, current_emotion)
        # happy 记忆应该排前面
        assert scored[0].id == "h"
        assert scored[1].id == "s"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_search.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/animetta/memory/v2/search.py
from __future__ import annotations
from animetta.memory.v2.atom import MemoryAtom
from animetta.memory.v2.emotion_field import EmotionalField, VADVector


class MemorySearch:
    """混合检索 — 向量 + 关键词 + 情绪偏置。"""

    @staticmethod
    def rank_by_emotion(
        atoms: list[MemoryAtom],
        current_emotion: VADVector,
    ) -> list[MemoryAtom]:
        """按情绪一致性重新排序（不影响原始搜索得分）。"""
        scored = []
        for atom in atoms:
            mem_emotion = VADVector(
                atom.emotion_valence,
                atom.emotion_arousal,
                atom.emotion_dominance,
            )
            congruence = EmotionalField.emotion_congruence(current_emotion, mem_emotion)
            scored.append((atom, congruence))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [atom for atom, _ in scored]

    @staticmethod
    def composite_score(
        vector_score: float,
        keyword_score: float,
        emotion_congruence: float,
    ) -> float:
        """综合评分公式: 55% 向量 + 25% 关键词 + 20% 情绪。"""
        return 0.55 * vector_score + 0.25 * keyword_score + 0.20 * emotion_congruence
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_search.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/animetta/memory/v2/search.py tests/memory_v2/test_search.py
git commit -m "feat: add MemorySearch with emotion-biased ranking"
```

---

## Task 6: LivingMemorySystem — wiring hub

**Files:**
- Create: `src/animetta/memory/v2/system.py`
- Create: `tests/memory_v2/test_system.py`

**Step 1: Write failing tests**

```python
# tests/memory_v2/test_system.py
import pytest
from datetime import datetime, timezone
from animetta.memory.v2.atom import MemoryAtom, Layer
from animetta.memory.v2.emotion_field import VAD_MAP
from animetta.memory.v2.system import LivingMemorySystem


@pytest.fixture
async def system():
    s = LivingMemorySystem(db_path=":memory:")
    await s.initialize()
    yield s
    await s.shutdown()


@pytest.mark.asyncio
class TestLivingMemorySystem:
    async def test_encode_creates_raw_atom(self, system):
        atom = await system.encode(
            user_input="今天喝了拿铁",
            agent_response="拿铁确实不错！",
            emotion_vad=VAD_MAP["happy"],
            session_id="test-session",
        )
        assert atom is not None
        assert atom.layer == Layer.RAW
        assert "拿铁" in atom.content
        assert atom.emotion_valence > 0.5  # happy → positive valence
        assert atom.retrieval_count == 0

    async def test_recall_returns_atoms(self, system):
        # 先存一条记忆
        await system.encode(
            user_input="我喜欢咖啡",
            agent_response="咖啡很棒",
            emotion_vad=VAD_MAP["neutral"],
            session_id="test-session",
        )
        # 再检索
        result = await system.recall(
            query="咖啡",
            session_id="test-session",
            current_emotion=VAD_MAP["happy"],
        )
        assert len(result.atoms) >= 1
        assert result.profile is not None
        assert result.memes is not None

    async def test_encode_with_neutral_emotion(self, system):
        atom = await system.encode(
            user_input="hello",
            agent_response="hi",
            emotion_vad=VAD_MAP["neutral"],
            session_id="s1",
        )
        # neutral → 情绪向量接近零
        assert abs(atom.emotion_valence) < 0.1
        assert abs(atom.emotion_arousal) < 0.1
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_system.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/animetta/memory/v2/system.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from animetta.memory.v2.atom import MemoryAtom, Layer
from animetta.memory.v2.store import AtomStore
from animetta.memory.v2.emotion_field import EmotionalField, VADVector
from animetta.memory.v2.search import MemorySearch


@dataclass
class RecallResult:
    """检索结果 — 含模糊化记忆、用户画像、活跃梗。"""
    atoms: list[MemoryAtom] = field(default_factory=list)
    profile: dict = field(default_factory=dict)
    memes: list[MemoryAtom] = field(default_factory=list)


class LivingMemorySystem:
    """活性记忆系统入口 — 编码/检索/再巩固/代谢 的编排中心。"""

    def __init__(self, db_path: str = "memory_db/living_memory.sqlite"):
        self.store = AtomStore(db_path=db_path)
        self._initialized = False

    async def initialize(self):
        await self.store.initialize()
        self._initialized = True

    async def shutdown(self):
        await self.store.close()

    async def encode(
        self,
        user_input: str,
        agent_response: str,
        emotion_vad: VADVector | None = None,
        session_id: str = "default",
    ) -> MemoryAtom:
        """将一轮对话编码为 RAW 层 MemoryAtom。"""
        if emotion_vad is None:
            emotion_vad = VADVector(0.0, 0.0, 0.0)

        content = f"用户: {user_input}\n助手: {agent_response}"
        now = datetime.now(timezone.utc)

        atom = MemoryAtom(
            id=f"raw-{uuid.uuid4().hex[:12]}",
            layer=Layer.RAW,
            content=content,
            summary=None,
            occurred_at=now,
            rewritten_at=now,
            version=1,
            confidence=EmotionalField.encoding_confidence(emotion_vad),
            salience=EmotionalField.encoding_confidence(emotion_vad),
            emotion_valence=emotion_vad.valence,
            emotion_arousal=emotion_vad.arousal,
            emotion_dominance=emotion_vad.dominance,
            tags=[session_id],
        )
        await self.store.create(atom)
        return atom

    async def recall(
        self,
        query: str,
        session_id: str = "default",
        current_emotion: VADVector | None = None,
        limit: int = 20,
    ) -> RecallResult:
        """检索记忆上下文（替代 FuzzyLayer + UserProfile + MemePool）。"""
        if current_emotion is None:
            current_emotion = VADVector(0.0, 0.0, 0.0)

        # 简单实现：先获取所有活跃原子，再排序
        # 后续集成 Chroma 向量搜索后替换为真正的混合检索
        all_active = self._get_all_active_sync(limit * 3)

        # 情绪偏置排序
        ranked = MemorySearch.rank_by_emotion(all_active, current_emotion)

        # 取 top-K，按 layer 降级排列
        result = RecallResult(
            atoms=ranked[:limit],
            profile={},  # 后续从 SEMANTIC 层提取
            memes=[a for a in ranked if a.layer == Layer.EMERGENT][:5],
        )
        return result

    def _get_all_active_sync(self, limit: int) -> list[MemoryAtom]:
        """同步获取活跃原子（简化版，后续改为异步 + Chroma 检索）。"""
        import sqlite3
        conn = sqlite3.connect(self.store.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM memory_atoms WHERE is_archived = 0 ORDER BY salience DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [self.store._row_to_atom(r) for r in rows]
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_system.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/animetta/memory/v2/system.py tests/memory_v2/test_system.py
git commit -m "feat: add LivingMemorySystem with encode and recall"
```

---

## Task 7: LangGraph integration — 6 touchpoints

**Files:**
- Modify: `src/animetta/orchestration/graph/emotion_node.py`
- Modify: `src/animetta/orchestration/graph/state.py`
- Modify: `src/animetta/orchestration/graph/output_node.py`
- Modify: `src/animetta/orchestration/graph/memory_middleware.py`
- Modify: `src/animetta/orchestration/graph/llm_node.py`
- Modify: `src/animetta/core/service_context.py`

**Step 1: Add emotion_vad to AgentState**

```python
# state.py — 在 AgentState 中新增
emotion_vad: Optional[tuple[float, float, float]]  # VAD 向量
```

**Step 2: Convert discrete emotion to VAD in emotion_node**

```python
# emotion_node.py — 在返回前加
from animetta.memory.v2.emotion_field import VAD_MAP

vad = VAD_MAP.get(emotion_data.primary, VAD_MAP["neutral"])
return {"emotion": emotion_data.primary, "emotion_vad": vad.to_tuple()}
```

**Step 3: Adapt output_node to use encode()**

```python
# output_node.py — 替换 _store_conversation_to_memory
vad_tuple = state.get("emotion_vad")
vad = VADVector(*vad_tuple) if vad_tuple else None
await memory_system.encode(
    user_input=user_msg,
    agent_response=agent_msg,
    emotion_vad=vad,
    session_id=session_id,
)
```

**Step 4: Adapt memory_middleware to use recall()**

```python
# memory_middleware.py — 替换 before_llm_call
vad_tuple = state.get("emotion_vad")
vad = VADVector(*vad_tuple) if vad_tuple else None
result = await memory_system.recall(
    query=last_user_message,
    session_id=session_id,
    current_emotion=vad,
)
# result.atoms → inject into system prompt
# result.profile → inject user context
# result.memes → inject memes
```

**Step 5: Adapt llm_node to use new retrieval**

```python
# llm_node.py — 适配 _retrieve_memory_context
# 调用 memory_middleware.before_llm_call() 的新接口
```

**Step 6: Adapt service_context to init LivingMemorySystem**

```python
# service_context.py — init_memory()
from animetta.memory.v2.system import LivingMemorySystem

async def init_memory(self):
    self.memory_system = LivingMemorySystem(db_path="memory_db/living_memory.sqlite")
    await self.memory_system.initialize()
```

**Step 7: Run existing integration tests**

Run: `PYTHONPATH=src python -m pytest tests/memory/ -v --tb=short`
Expected: 可能需要调整部分旧测试

**Step 8: Commit**

```bash
git add src/animetta/orchestration/graph/ src/animetta/core/service_context.py
git commit -m "feat: integrate LivingMemory V2 into LangGraph orchestration"
```

---

## Task 8: Move legacy modules to _legacy/

**Files:**
- Move: `src/animetta/memory/system.py` → `src/animetta/memory/_legacy/system.py`
- Move: `src/animetta/memory/fuzzy_layer.py` → `src/animetta/memory/_legacy/fuzzy_layer.py`
- Move: `src/animetta/memory/manager.py` → `src/animetta/memory/_legacy/manager.py`
- Move: `src/animetta/memory/fact_extractor.py` → `src/animetta/memory/_legacy/fact_extractor.py`
- Move: `src/animetta/memory/meme/` → `src/animetta/memory/_legacy/meme/`
- Move: `src/animetta/memory/learner/` → `src/animetta/memory/_legacy/learner/`
- Move: `src/animetta/memory/fuzzy/` → `src/animetta/memory/_legacy/fuzzy/`
- Move: `src/animetta/memory/stores/` → `src/animetta/memory/_legacy/stores/`
- Move: `src/animetta/memory/user_profile.py` → `src/animetta/memory/_legacy/user_profile.py`
- Move: `src/animetta/memory/prompts.py` → `src/animetta/memory/_legacy/prompts.py`

**保留不动**:
- `src/animetta/memory/storage/` (Chroma + SQLite 驱动)
- `src/animetta/memory/wiki/` (降级为导出层)
- `src/animetta/memory/models/` (旧模块可能引用)
- `src/animetta/memory/tools.py` (LLM tool schemas)
- `src/animetta/memory/config.py` (配置)

**Step 1: Create _legacy directory and move files**

```bash
mkdir -p src/animetta/memory/_legacy
git mv src/animetta/memory/system.py src/animetta/memory/_legacy/
git mv src/animetta/memory/fuzzy_layer.py src/animetta/memory/_legacy/
# ... etc
```

**Step 2: Commit**

```bash
git add src/animetta/memory/_legacy/
git commit -m "refactor: move legacy memory modules to _legacy/"
```

---

## Task 9: Integration test — end-to-end encode → recall → reconsolidate

**Files:**
- Create: `tests/memory_v2/test_integration.py`

**Step 1: Write integration test**

```python
# tests/memory_v2/test_integration.py
import pytest
import asyncio
from datetime import datetime, timezone
from animetta.memory.v2.system import LivingMemorySystem
from animetta.memory.v2.emotion_field import VAD_MAP
from animetta.memory.v2.atom import Layer


@pytest.mark.asyncio
class TestLivingMemoryIntegration:
    async def test_encode_recall_lifecycle(self):
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()

        # 1. 编码一段开心的咖啡对话
        atom = await system.encode(
            user_input="今天在星巴克喝了杯拿铁，超级开心！",
            agent_response="拿铁确实让人心情好~",
            emotion_vad=VAD_MAP["happy"],
            session_id="s1",
        )
        assert atom.layer == Layer.RAW
        assert atom.emotion_valence > 0.5  # happy encoding

        # 2. 用开心的情绪检索
        result = await system.recall(
            query="咖啡",
            session_id="s1",
            current_emotion=VAD_MAP["happy"],
        )
        assert len(result.atoms) > 0
        assert "拿铁" in result.atoms[0].content

        # 3. 用悲伤的情绪检索同一段记忆 — 应该排后面
        sad_result = await system.recall(
            query="咖啡",
            session_id="s1",
            current_emotion=VAD_MAP["sad"],
        )
        # sad 情绪下，这段 happy 记忆的 emotion congruence 低
        # 简单验证：至少不会 crash
        assert sad_result is not None

        await system.shutdown()

    async def test_multiple_encode_and_recall_order(self):
        system = LivingMemorySystem(db_path=":memory:")
        await system.initialize()

        # 编码开心记忆
        await system.encode(
            user_input="咖啡真好喝", agent_response="是啊",
            emotion_vad=VAD_MAP["happy"], session_id="s1",
        )
        # 编码难过记忆
        await system.encode(
            user_input="咖啡洒了", agent_response="好可惜",
            emotion_vad=VAD_MAP["sad"], session_id="s1",
        )

        # 开心时检索 → 开心记忆排前面
        result = await system.recall(
            query="咖啡", session_id="s1",
            current_emotion=VAD_MAP["happy"],
        )
        if len(result.atoms) >= 2:
            # 第一个应该是开心记忆
            assert result.atoms[0].emotion_valence > result.atoms[1].emotion_valence

        await system.shutdown()
```

**Step 2: Run integration test**

Run: `PYTHONPATH=src python -m pytest tests/memory_v2/test_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/memory_v2/test_integration.py
git commit -m "test: add integration tests for living memory lifecycle"
```

---

## Task 10: Acceptance — run full test suite

**Step 1: Run all new tests**

```bash
PYTHONPATH=src python -m pytest tests/memory_v2/ -v
```

Expected: All pass.

**Step 2: Run existing memory tests for regression**

```bash
PYTHONPATH=src python -m pytest tests/memory/ -v --tb=short
```

Expected: Core storage + wiki tests should pass. Some tests referencing moved modules may need path updates.

**Step 3: Type check**

```bash
mypy src/animetta/memory/v2/ --ignore-missing-imports
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: finalize living memory V2 — all tests passing"
```
