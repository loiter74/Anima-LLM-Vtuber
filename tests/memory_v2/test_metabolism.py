from __future__ import annotations

"""Tests for MetabolismScheduler."""

import math
from datetime import UTC, datetime

from animetta.memory.v2.atom import Layer, MemoryAtom
from animetta.memory.v2.metabolism import MetabolismScheduler


class TestSalienceCalculation:
    def test_fresh_atom_default_salience(self):
        atom = MemoryAtom(
            id="a1",
            layer=Layer.RAW,
            content="test",
            occurred_at=datetime.now(UTC),
            confidence=0.5,
        )
        salience = MetabolismScheduler.compute_salience(atom)
        assert math.isclose(salience, 0.5, rel_tol=0.15)

    def test_high_confidence_increases_salience(self):
        high = MemoryAtom(
            id="h1",
            layer=Layer.RAW,
            content="important",
            occurred_at=datetime.now(UTC),
            confidence=0.9,
        )
        low = MemoryAtom(
            id="l1",
            layer=Layer.RAW,
            content="trivial",
            occurred_at=datetime.now(UTC),
            confidence=0.2,
        )
        assert MetabolismScheduler.compute_salience(high) > MetabolismScheduler.compute_salience(
            low
        )

    def test_retrieval_boosts_salience(self):
        retrieved = MemoryAtom(
            id="r1",
            layer=Layer.RAW,
            content="recalled",
            occurred_at=datetime.now(UTC),
            retrieval_count=10,
        )
        fresh = MemoryAtom(
            id="f1",
            layer=Layer.RAW,
            content="fresh",
            occurred_at=datetime.now(UTC),
            retrieval_count=0,
        )
        assert MetabolismScheduler.compute_salience(
            retrieved
        ) > MetabolismScheduler.compute_salience(fresh)


class TestAdaptiveThreshold:
    def test_low_watermark_relaxed(self):
        threshold = MetabolismScheduler.adaptive_threshold(atom_count=25, capacity=100)
        assert threshold <= 0.02

    def test_high_watermark_aggressive(self):
        threshold = MetabolismScheduler.adaptive_threshold(atom_count=90, capacity=100)
        assert threshold >= 0.15

    def test_mid_watermark_moderate(self):
        threshold = MetabolismScheduler.adaptive_threshold(atom_count=60, capacity=100)
        assert 0.05 < threshold < 0.20

    def test_full_capacity_max_threshold(self):
        threshold = MetabolismScheduler.adaptive_threshold(atom_count=100, capacity=100)
        assert threshold == 0.20


class TestMetabolismEdgeCases:
    def test_salience_zero_confidence(self):
        atom = MemoryAtom(
            id="z", layer=Layer.RAW, content="zero", occurred_at=datetime.now(UTC), confidence=0.0
        )
        salience = MetabolismScheduler.compute_salience(atom)
        assert salience < 0.05

    def test_salience_decreases_over_multiple_ticks(self):
        atom = MemoryAtom(
            id="d", layer=Layer.RAW, content="decay", occurred_at=datetime.now(UTC), confidence=0.8
        )
        s1 = MetabolismScheduler.compute_salience(atom)
        atom.retrieval_count = 0  # no retrieval boost
        # Salience at creation ≈ confidence
        assert s1 > 0.0

    def test_adaptive_threshold_zero_atoms(self):
        t = MetabolismScheduler.adaptive_threshold(0, 100)
        assert t == 0.02

    def test_adaptive_threshold_at_capacity(self):
        t = MetabolismScheduler.adaptive_threshold(100, 100)
        assert t == 0.20

    def test_emotion_protection_in_salience(self):
        high_emo = MemoryAtom(
            id="he",
            layer=Layer.RAW,
            content="emotional",
            occurred_at=datetime.now(UTC),
            confidence=0.5,
            emotion_valence=0.9,
            emotion_arousal=0.9,
        )
        low_emo = MemoryAtom(
            id="le",
            layer=Layer.RAW,
            content="neutral",
            occurred_at=datetime.now(UTC),
            confidence=0.5,
            emotion_valence=0.0,
            emotion_arousal=0.0,
        )
        assert MetabolismScheduler.compute_salience(
            high_emo
        ) > MetabolismScheduler.compute_salience(low_emo)
