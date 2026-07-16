"""CharacterMemoryFilter — recall filtering and ranking based on character persona.

Filters memory atoms by knowledge boundaries (hard exclude unknown domains)
and re-ranks by MBTI personality preference.
"""

from __future__ import annotations

from animetta.memory.v2.atom import Layer, MemoryAtom


class CharacterMemoryFilter:
    """Filters and ranks MemoryAtoms based on a character's persona configuration.

    Two-stage pipeline:
    1. filter_by_boundaries — hard exclude atoms belonging to unknown knowledge domains
    2. rank_by_persona — re-order atoms based on MBTI dimension preferences
    """

    @staticmethod
    def filter_by_boundaries(
        atoms: list[MemoryAtom],
        known: list[str],
        unknown: list[str],
        query: str = "",
    ) -> list[MemoryAtom]:
        """Hard filter: exclude atoms whose content matches unknown knowledge domains.

        Uses keyword substring matching against atom content and summary.
        Known domains match adds no penalty; unknown domains match → excluded.

        Args:
            atoms: Recall results to filter.
            known: Domains the character knows (not used for filtering, informational).
            unknown: Domains the character does NOT understand — matched atoms excluded.
            query: Original search query (informational, unused in current matching).

        Returns:
            Filtered atom list.
        """
        if not unknown:
            return atoms

        filtered: list[MemoryAtom] = []
        for atom in atoms:
            text = (atom.summary or "") + " " + atom.content
            excluded = False
            for domain in unknown:
                if domain.lower() in text.lower():
                    excluded = True
                    break
            if not excluded:
                filtered.append(atom)

        return filtered

    @staticmethod
    def rank_by_persona(
        atoms: list[MemoryAtom],
        mbti_ei: int = 50,
        mbti_sn: int = 50,
        mbti_tf: int = 50,
        mbti_jp: int = 50,
    ) -> list[MemoryAtom]:
        """Re-rank atoms by MBTI personality congruence.

        Scoring rules:
        - Feeling-dominant (TF < 45): prefer emotional memories (higher arousal + valence abs)
        - Thinking-dominant (TF > 55): prefer factual/calm memories
        - Judging (JP > 55): slight preference for SEMANTIC layer (explicit beliefs)
        - Perceiving (JP < 45): slight preference for RAW/EPISODIC (experiential)

        Args:
            atoms: Recall results to rank.
            mbti_ei: E/I dimension (0=introversion, 100=extraversion).
            mbti_sn: S/N dimension (0=sensing, 100=intuition).
            mbti_tf: T/F dimension (0=feeling, 100=thinking).
            mbti_jp: J/P dimension (0=perceiving, 100=judging).

        Returns:
            Re-ordered atom list.
        """
        scored: list[tuple[MemoryAtom, float]] = []
        for atom in atoms:
            score: float = 0.0

            # Feeling/Thinking bias
            if mbti_tf < 45:
                # Feeling — prefer emotionally charged memories
                score += abs(atom.emotion_valence) * 0.10 + atom.emotion_arousal * 0.15
            elif mbti_tf > 55:
                # Thinking — prefer calm/factual memories
                score += (1.0 - abs(atom.emotion_valence)) * 0.10

            # Judging/Perceiving bias
            if mbti_jp > 55 and atom.layer == Layer.SEMANTIC:
                score += 0.05
            elif mbti_jp < 45 and atom.layer in (Layer.RAW, Layer.EPISODIC):
                score += 0.03

            scored.append((atom, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [atom for atom, _ in scored]

    @staticmethod
    def apply(
        atoms: list[MemoryAtom],
        known: list[str] | None = None,
        unknown: list[str] | None = None,
        mbti_ei: int = 50,
        mbti_sn: int = 50,
        mbti_tf: int = 50,
        mbti_jp: int = 50,
    ) -> list[MemoryAtom]:
        """Convenience method: apply both filter and rank in one call.

        Args:
            atoms: Recall results.
            known: Known domains (informational).
            unknown: Unknown domains (hard filter).
            mbti_ei, mbti_sn, mbti_tf, mbti_jp: MBTI dimensions.

        Returns:
            Filtered and ranked atom list.
        """
        filtered = CharacterMemoryFilter.filter_by_boundaries(
            atoms,
            known=known or [],
            unknown=unknown or [],
        )
        return CharacterMemoryFilter.rank_by_persona(
            filtered,
            mbti_ei=mbti_ei,
            mbti_sn=mbti_sn,
            mbti_tf=mbti_tf,
            mbti_jp=mbti_jp,
        )
