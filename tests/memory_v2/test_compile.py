from __future__ import annotations

"""Tests for CompileEngine layer progression."""

from datetime import UTC, datetime, timedelta

import pytest

from animetta.memory.v2.atom import (
    Layer,
    MemoryAtom,
    MemoryScope,
    MemoryVisibility,
    RelationType,
)
from animetta.memory.v2.compile import COMPILE_TRIGGERS, CompileEngine


def make_atom(layer: Layer, content: str, hours_ago: float = 2.0) -> MemoryAtom:
    return MemoryAtom(
        id=f"{layer.name}-{content[:8]}",
        layer=layer,
        content=content,
        occurred_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        confidence=0.7,
    )


class TestCompileEngine:
    def test_compile_insufficient_atoms(self):
        """Less than 2 atoms → no compilation."""
        engine = CompileEngine()
        result = asyncio_run(engine.compile_layer(
            [make_atom(Layer.RAW, "one conversation")],
            Layer.EPISODIC,
        ))
        assert result is None

    def test_compile_wrong_layer_direction(self):
        """Cannot compile upward — source must be lower layer."""
        engine = CompileEngine()
        result = asyncio_run(engine.compile_layer(
            [make_atom(Layer.SEMANTIC, "knowledge", 48),
             make_atom(Layer.SEMANTIC, "more knowledge", 72)],
            Layer.EPISODIC,  # EPISODIC < SEMANTIC — wrong direction
        ))
        assert result is None

    def test_compile_rule_based_fallback(self):
        """Without LLM, rule-based fallback concatenates first sentences."""
        engine = CompileEngine()  # no LLM
        atoms = [
            make_atom(Layer.RAW, "用户今天喝了拿铁。很开心。", 2),
            make_atom(Layer.RAW, "用户下午又喝了美式。说苦。", 3),
        ]
        result = asyncio_run(engine.compile_layer(atoms, Layer.EPISODIC))
        assert result is not None
        assert result.layer == Layer.EPISODIC
        assert len(result.source_ids) == 2
        assert result.summary is not None
        assert len(result.summary) > 0

    def test_compile_preserves_emotion(self):
        engine = CompileEngine()
        atoms = [
            make_atom(Layer.RAW, "开心的事", 2),
            make_atom(Layer.RAW, "也很开心", 3),
        ]
        atoms[0].emotion_valence = 0.8
        atoms[1].emotion_valence = 0.6
        result = asyncio_run(engine.compile_layer(atoms, Layer.EPISODIC))
        assert result.emotion_valence == pytest.approx(0.7, rel=0.1)

    def test_compile_creates_relations(self):
        engine = CompileEngine()
        atoms = [
            make_atom(Layer.RAW, "对话1", 2),
            make_atom(Layer.RAW, "对话2", 3),
        ]
        result = asyncio_run(engine.compile_layer(atoms, Layer.EPISODIC))
        assert len(result.relations) == 2
        assert all(r.relation_type == RelationType.DERIVES for r in result.relations)

    def test_compile_inherits_private_viewer_boundary(self):
        engine = CompileEngine()
        atoms = [
            make_atom(Layer.RAW, "viewer memory one", 2),
            make_atom(Layer.RAW, "viewer memory two", 3),
        ]
        for atom in atoms:
            atom.scope = MemoryScope.VIEWER
            atom.visibility = MemoryVisibility.PRIVATE
            atom.subject_ids = ["bilibili:42"]
            atom.origin = {"channel": "bilibili", "stream_id": "live:1"}

        result = asyncio_run(engine.compile_layer(atoms, Layer.EPISODIC))

        assert result.scope is MemoryScope.VIEWER
        assert result.visibility is MemoryVisibility.PRIVATE
        assert result.subject_ids == ["bilibili:42"]
        assert result.origin == atoms[0].origin


class TestEligibility:
    def test_eligible_excludes_wrong_layer(self):
        atoms = [
            make_atom(Layer.EPISODIC, "episode", 48),
        ]
        eligible = CompileEngine.get_eligible_atoms(
            atoms, Layer.RAW, COMPILE_TRIGGERS[Layer.RAW]
        )
        assert len(eligible) == 0

    def test_eligible_excludes_too_new(self):
        atoms = [
            make_atom(Layer.RAW, "fresh", 0.1),  # only 6 minutes old
        ]
        eligible = CompileEngine.get_eligible_atoms(
            atoms, Layer.RAW, COMPILE_TRIGGERS[Layer.RAW]
        )
        assert len(eligible) == 0

    def test_eligible_includes_old_enough(self):
        atoms = [
            make_atom(Layer.RAW, "old enough", 3.0),  # 3 hours
        ]
        eligible = CompileEngine.get_eligible_atoms(
            atoms, Layer.RAW, COMPILE_TRIGGERS[Layer.RAW]
        )
        assert len(eligible) == 1

    def test_eligible_excludes_already_compiled(self):
        from animetta.memory.v2.atom import Relation
        atom = make_atom(Layer.RAW, "already compiled", 3)
        atom.relations.append(Relation(
            source_id=atom.id, target_id="other",
            relation_type=RelationType.DERIVES,
        ))
        eligible = CompileEngine.get_eligible_atoms(
            [atom], Layer.RAW, COMPILE_TRIGGERS[Layer.RAW]
        )
        assert len(eligible) == 0


class TestCompileTriggers:
    def test_raw_to_episodic_trigger(self):
        t = COMPILE_TRIGGERS[Layer.RAW]
        assert t.min_atoms == 5
        assert t.min_age_hours == 1.0
        assert t.target_layer == Layer.EPISODIC

    def test_episodic_to_semantic_trigger(self):
        t = COMPILE_TRIGGERS[Layer.EPISODIC]
        assert t.target_layer == Layer.SEMANTIC

    def test_semantic_to_emergent_trigger(self):
        t = COMPILE_TRIGGERS[Layer.SEMANTIC]
        assert t.target_layer == Layer.EMERGENT


def asyncio_run(coro):
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already in event loop — create new one in thread
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()

class TestCompileEdgeCases:
    def test_compile_single_atom_returns_none(self):
        engine = CompileEngine()
        result = asyncio_run(engine.compile_layer(
            [make_atom(Layer.RAW, "single")], Layer.EPISODIC
        ))
        assert result is None

    def test_compile_preserves_derives_relations(self):
        engine = CompileEngine()
        atoms = [make_atom(Layer.RAW, f"conv{i}", 2 + i) for i in range(3)]
        result = asyncio_run(engine.compile_layer(atoms, Layer.EPISODIC))
        assert result is not None
        assert len(result.relations) == 3
        assert all(r.relation_type == RelationType.DERIVES for r in result.relations)
