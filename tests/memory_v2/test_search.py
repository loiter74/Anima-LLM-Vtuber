from __future__ import annotations

"""Tests for MemorySearch emotion-biased ranking."""

from datetime import UTC, datetime

from animetta.memory.v2.atom import Layer, MemoryAtom
from animetta.memory.v2.emotion_field import VAD_MAP
from animetta.memory.v2.search import MemorySearch


class TestSearchScoring:
    def test_emotion_biased_ranking(self):
        """Happy memory ranks first when querying with happy emotion."""
        atoms = [
            MemoryAtom(
                id="happy_mem", layer=Layer.SEMANTIC, content="咖啡很好喝",
                occurred_at=datetime.now(UTC),
                emotion_valence=0.8, emotion_arousal=0.6, emotion_dominance=0.7,
                confidence=0.8, salience=0.8,
            ),
            MemoryAtom(
                id="sad_mem", layer=Layer.SEMANTIC, content="咖啡很苦",
                occurred_at=datetime.now(UTC),
                emotion_valence=-0.8, emotion_arousal=0.3, emotion_dominance=-0.5,
                confidence=0.8, salience=0.8,
            ),
        ]
        current_emotion = VAD_MAP["happy"]

        scored = MemorySearch.rank_by_emotion(atoms, current_emotion)
        assert scored[0].id == "happy_mem"
        assert scored[1].id == "sad_mem"

    def test_composite_score_range(self):
        score = MemorySearch.composite_score(
            vector_score=0.9, keyword_score=0.5, emotion_congruence=1.0,
        )
        assert 0.0 <= score <= 1.0

    def test_composite_score_weights(self):
        """Verify the 55/25/20 split produces expected value."""
        score = MemorySearch.composite_score(1.0, 0.0, 0.0)
        assert score == 0.55
        score = MemorySearch.composite_score(0.0, 1.0, 0.0)
        assert score == 0.25
        score = MemorySearch.composite_score(0.0, 0.0, 1.0)
        assert score == 0.20
