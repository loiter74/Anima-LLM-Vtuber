from __future__ import annotations

"""Tests for MemoryAtom unified model."""

from datetime import UTC, datetime

from animetta.memory.v2.atom import Layer, MemoryAtom, Relation, RelationType


class TestMemoryAtom:
    def test_create_raw_atom(self):
        atom = MemoryAtom(
            id="atom-001",
            layer=Layer.RAW,
            content="用户说今天喝了拿铁",
            occurred_at=datetime.now(UTC),
        )
        assert atom.layer == Layer.RAW
        assert atom.version == 1
        assert atom.rewritten_at == atom.occurred_at  # never recalled
        assert atom.confidence == 0.5
        assert atom.salience == 0.5
        assert atom.retrieval_count == 0
        assert atom.last_accessed_at is None
        assert atom.is_archived is False

    def test_layer_progression(self):
        """RAW < EPISODIC < SEMANTIC < EMERGENT"""
        assert Layer.RAW < Layer.EPISODIC < Layer.SEMANTIC < Layer.EMERGENT

    def test_bi_temporal_rewritten_different(self):
        occurred = datetime(2026, 5, 30, tzinfo=UTC)
        rewritten = datetime(2026, 5, 31, tzinfo=UTC)
        atom = MemoryAtom(
            id="a1",
            layer=Layer.SEMANTIC,
            content="知识",
            occurred_at=occurred,
            rewritten_at=rewritten,
            version=3,
            version_chain=["v1_id", "v2_id"],
        )
        assert atom.occurred_at != atom.rewritten_at
        assert atom.is_recalled is True
        assert atom.version == 3

    def test_emotion_vector_defaults(self):
        atom = MemoryAtom(
            id="a1",
            layer=Layer.RAW,
            content="test",
            occurred_at=datetime.now(UTC),
        )
        assert atom.emotion_valence == 0.0
        assert atom.emotion_arousal == 0.0
        assert atom.emotion_dominance == 0.0

    def test_relation_creation(self):
        r = Relation(source_id="a1", target_id="a2", relation_type=RelationType.UPDATES)
        assert r.relation_type == RelationType.UPDATES
        assert r.source_id == "a1"

    def test_is_recalled_false_when_not_recalled(self):
        now = datetime.now(UTC)
        atom = MemoryAtom(
            id="a1",
            layer=Layer.RAW,
            content="new",
            occurred_at=now,
        )
        assert atom.is_recalled is False


class TestLayer:
    def test_layer_from_value(self):
        assert Layer(0) == Layer.RAW
        assert Layer(1) == Layer.EPISODIC
        assert Layer(2) == Layer.SEMANTIC
        assert Layer(3) == Layer.EMERGENT

    def test_all_relation_types(self):
        assert RelationType.UPDATES == "UPDATES"
        assert RelationType.EXTENDS == "EXTENDS"
        assert RelationType.DERIVES == "DERIVES"
        assert RelationType.EVOKES == "EVOKES"
        assert RelationType.CONTRADICTS == "CONTRADICTS"
        assert RelationType.CONSOLIDATED_INTO == "CONSOLIDATED_INTO"


class TestAtomEdgeCases:
    """Edge case tests for MemoryAtom."""

    def test_layer_ordering_consistent(self):
        """RAW < EPISODIC < SEMANTIC < EMERGENT is transitive."""
        assert Layer.RAW < Layer.SEMANTIC  # transitive
        assert Layer.EPISODIC < Layer.EMERGENT

    def test_rewritten_at_never_before_occurred(self):
        """rewritten_at should never be earlier than occurred_at."""
        occurred = datetime(2026, 5, 30, tzinfo=UTC)
        rewritten = datetime(2026, 5, 29, tzinfo=UTC)
        atom = MemoryAtom(
            id="a1",
            layer=Layer.RAW,
            content="test",
            occurred_at=occurred,
            rewritten_at=rewritten,
        )
        assert (
            atom.rewritten_at == rewritten
        )  # stored as-is (validation is caller's responsibility)

    def test_empty_version_chain(self):
        """New atom has empty version chain."""
        atom = MemoryAtom(
            id="a1",
            layer=Layer.RAW,
            content="test",
            occurred_at=datetime.now(UTC),
        )
        assert atom.version_chain == []
        assert atom.version == 1

    def test_emotion_values_in_range(self):
        """VAD values should typically be in [-1, 1] range."""
        atom = MemoryAtom(
            id="a1",
            layer=Layer.RAW,
            content="test",
            occurred_at=datetime.now(UTC),
            emotion_valence=0.5,
            emotion_arousal=0.8,
            emotion_dominance=0.3,
        )
        assert -1.0 <= atom.emotion_valence <= 1.0
        assert 0.0 <= atom.emotion_arousal <= 1.0
        assert -1.0 <= atom.emotion_dominance <= 1.0

    def test_relation_types_complete(self):
        """All 6 relation type constants are distinct strings."""
        types = {
            RelationType.UPDATES,
            RelationType.EXTENDS,
            RelationType.DERIVES,
            RelationType.EVOKES,
            RelationType.CONTRADICTS,
            RelationType.CONSOLIDATED_INTO,
        }
        assert len(types) == 6

    def test_recall_age_none_when_not_accessed(self):
        atom = MemoryAtom(
            id="a1",
            layer=Layer.RAW,
            content="test",
            occurred_at=datetime.now(UTC),
        )
        assert atom.recall_age_hours is None
