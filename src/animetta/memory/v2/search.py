"""MemorySearch — hybrid retrieval with emotion bias.

Composite scoring: 55% vector + 25% keyword + 20% emotion congruence.
"""

from __future__ import annotations

from animetta.memory.v2.atom import MemoryAtom
from animetta.memory.v2.emotion_field import EmotionalField, VADVector


class MemorySearch:
    """Hybrid memory search with mood-congruent recall bias."""

    @staticmethod
    def rank_by_emotion(
        atoms: list[MemoryAtom],
        current_emotion: VADVector,
    ) -> list[MemoryAtom]:
        """Reorder atoms by emotion congruence with current emotional state.

        Atoms with emotion vectors similar to the current emotion rank higher.
        This implements mood-congruent recall (Bower, 1981).
        """
        scored: list[tuple[MemoryAtom, float]] = []
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
        """Composite search score.

        55% vector similarity + 25% keyword match + 20% emotion congruence.
        """
        return 0.55 * vector_score + 0.25 * keyword_score + 0.20 * emotion_congruence
