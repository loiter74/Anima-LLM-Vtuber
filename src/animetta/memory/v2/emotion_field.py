"""EmotionalField — VAD vector model permeating all memory operations.

Replaces 14 discrete emotion labels with a continuous 3D vector space
(Valence / Arousal / Dominance) that permeates encoding, retrieval,
reconsolidation, and metabolism.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VADVector:
    """Valence-Arousal-Dominance 3D emotion vector.

    Valence:   -1.0 (unpleasant) to +1.0 (pleasant)
    Arousal:    0.0 (calm/sleepy) to 1.0 (excited/tense)
    Dominance: -1.0 (submissive) to +1.0 (dominant/in-control)
    """

    valence: float
    arousal: float
    dominance: float

    def to_tuple(self) -> tuple[float, float, float]:
        return (self.valence, self.arousal, self.dominance)

    @property
    def intensity(self) -> float:
        """Overall emotional intensity (magnitude)."""
        return math.sqrt(self.valence**2 + self.arousal**2 + self.dominance**2)


# 14 discrete emotion labels → VAD vector mapping
# Based on Russell's circumplex model of affect with empirical tuning
VAD_MAP: dict[str, VADVector] = {
    "happy": VADVector(0.81, 0.51, 0.67),
    "excited": VADVector(0.88, 0.85, 0.78),
    "love": VADVector(0.89, 0.45, 0.42),
    "proud": VADVector(0.72, 0.48, 0.79),
    "neutral": VADVector(0.00, 0.00, 0.00),
    "thinking": VADVector(0.08, -0.28, 0.33),
    "confused": VADVector(-0.22, 0.32, -0.48),
    "surprised": VADVector(0.31, 0.82, -0.28),
    "suspicious": VADVector(-0.42, 0.38, -0.21),
    "shy": VADVector(0.12, 0.38, -0.71),
    "tired": VADVector(-0.13, -0.59, -0.41),
    "resigned": VADVector(-0.33, -0.52, -0.61),
    "sad": VADVector(-0.77, -0.33, -0.58),
    "angry": VADVector(-0.81, 0.82, 0.48),
}


class EmotionalField:
    """Emotional field — provides all emotion-related computations.

    The field permeates four operations:
      Encoding  — arousal drives initial confidence (flashbulb memory)
      Retrieval — mood-congruent recall biases search results
      Reconsolidation — current emotion colors rewritten content
      Metabolism — emotional intensity protects against decay
    """

    @staticmethod
    def cosine_similarity(a: VADVector, b: VADVector) -> float:
        """Compute cosine similarity between two VAD vectors."""
        dot = a.valence * b.valence + a.arousal * b.arousal + a.dominance * b.dominance
        mag_a = math.sqrt(a.valence**2 + a.arousal**2 + a.dominance**2)
        mag_b = math.sqrt(b.valence**2 + b.arousal**2 + b.dominance**2)
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    @staticmethod
    def emotion_congruence(current: VADVector, memory: VADVector) -> float:
        """Compute mood-congruent recall bias.

        High-arousal states amplify the congruence effect —
        intense emotions produce stronger retrieval bias toward
        emotionally congruent memories (Bower, 1981).
        """
        cos = EmotionalField.cosine_similarity(current, memory)
        arousal_boost = 1.0 + 0.5 * current.arousal
        return cos * arousal_boost

    @staticmethod
    def encoding_confidence(emotion: VADVector) -> float:
        """Compute initial confidence from emotion intensity.

        High-arousal events get higher confidence (flashbulb memory effect).
        Extreme valence (very positive or very negative) also boosts encoding.
        """
        base = 0.5
        arousal_effect = 0.4 * emotion.arousal
        valence_effect = 0.1 * abs(emotion.valence)
        return min(1.0, base + arousal_effect + valence_effect)

    @staticmethod
    def metabolism_protection(emotion: VADVector) -> float:
        """Compute emotion-based protection against metabolic decay.

        Highly emotional memories (extreme valence × high arousal) decay slower.
        Flashbulb memories persist (Brown & Kulik, 1977).
        """
        return 1.0 + 0.3 * abs(emotion.valence) * emotion.arousal

    @staticmethod
    def emotion_shift(current: VADVector, memory: VADVector, max_shift: float = 0.2) -> VADVector:
        """Compute new emotion vector by shifting memory toward current.

        Used during reconsolidation: each recall slightly shifts the stored
        emotion toward the current emotional state. Shift is bounded.
        """

        def _shift(old: float, new: float) -> float:
            delta = (new - old) * 0.15  # 15% toward current per reconsolidation
            delta = max(-max_shift, min(max_shift, delta))
            return max(-1.0, min(1.0, old + delta))

        return VADVector(
            valence=_shift(memory.valence, current.valence),
            arousal=_shift(memory.arousal, current.arousal),
            dominance=_shift(memory.dominance, current.dominance),
        )
