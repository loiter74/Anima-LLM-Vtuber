from __future__ import annotations

"""Tests for EmotionalField VAD vector model."""

import math

from animetta.memory.v2.emotion_field import VAD_MAP, EmotionalField, VADVector


class TestVADMap:
    def test_all_14_emotions_mapped(self):
        expected = {
            "happy",
            "sad",
            "angry",
            "surprised",
            "neutral",
            "thinking",
            "confused",
            "love",
            "shy",
            "excited",
            "suspicious",
            "tired",
            "proud",
            "resigned",
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
        assert v.arousal < 0.0

    def test_neutral_is_zero(self):
        v = VAD_MAP["neutral"]
        assert v.valence == 0.0
        assert v.arousal == 0.0
        assert v.dominance == 0.0

    def test_to_tuple(self):
        v = VADVector(0.5, 0.3, 0.1)
        assert v.to_tuple() == (0.5, 0.3, 0.1)


class TestEmotionalField:
    def test_cosine_similarity_same(self):
        v = VADVector(0.8, 0.6, 0.7)
        sim = EmotionalField.cosine_similarity(v, v)
        assert math.isclose(sim, 1.0, rel_tol=1e-5)

    def test_cosine_similarity_opposite(self):
        v1 = VADVector(1.0, 0.0, 0.0)
        v2 = VADVector(-1.0, 0.0, 0.0)
        sim = EmotionalField.cosine_similarity(v1, v2)
        assert math.isclose(sim, -1.0, rel_tol=1e-5)

    def test_emotion_congruence_happy_happy(self):
        current = VAD_MAP["happy"]
        memory = VAD_MAP["happy"]
        congruence = EmotionalField.emotion_congruence(current, memory)
        assert congruence > 0.8

    def test_emotion_congruence_happy_sad(self):
        current = VAD_MAP["happy"]
        memory = VAD_MAP["sad"]
        congruence = EmotionalField.emotion_congruence(current, memory)
        assert congruence < 0.3

    def test_encoding_confidence_high_arousal(self):
        high = VADVector(0.0, 0.9, 0.0)
        low = VADVector(0.0, 0.1, 0.0)
        assert EmotionalField.encoding_confidence(high) > EmotionalField.encoding_confidence(low)

    def test_encoding_confidence_bounded(self):
        """Confidence should never exceed 1.0."""
        extreme = VADVector(1.0, 1.0, 1.0)
        conf = EmotionalField.encoding_confidence(extreme)
        assert conf <= 1.0

    def test_metabolism_protection_neutral(self):
        """Neutral emotion → no extra protection."""
        neutral = VADVector(0.0, 0.0, 0.0)
        protection = EmotionalField.metabolism_protection(neutral)
        assert math.isclose(protection, 1.0)

    def test_metabolism_protection_intense(self):
        """Intense emotion → extra decay protection."""
        intense = VADVector(0.9, 0.9, 0.0)
        protection = EmotionalField.metabolism_protection(intense)
        assert protection > 1.0

    def test_emotion_shift_toward_current(self):
        """Reconsolidation shifts memory emotion toward current."""
        memory = VAD_MAP["neutral"]  # (0, 0, 0)
        current = VAD_MAP["happy"]  # (0.81, 0.51, 0.67)
        shifted = EmotionalField.emotion_shift(current, memory)
        # Should move toward happy
        assert shifted.valence > 0.0
        assert shifted.arousal > 0.0

    def test_emotion_shift_bounded(self):
        """Shift magnitude should be bounded."""
        memory = VADVector(-1.0, 1.0, -1.0)
        current = VADVector(1.0, 0.0, 1.0)
        shifted = EmotionalField.emotion_shift(current, memory, max_shift=0.2)
        # Should not flip signs
        assert shifted.valence < 0.0  # still mostly negative
        assert shifted.arousal > 0.0  # still high (shift bounded)


class TestEmotionalFieldEdgeCases:
    def test_cosine_zero_vector(self):
        zero = VADVector(0.0, 0.0, 0.0)
        v = VADVector(1.0, 0.0, 0.0)
        assert EmotionalField.cosine_similarity(zero, v) == 0.0

    def test_cosine_orthogonal(self):
        v1 = VADVector(1.0, 0.0, 0.0)
        v2 = VADVector(0.0, 1.0, 0.0)
        sim = EmotionalField.cosine_similarity(v1, v2)
        assert abs(sim) < 0.01

    def test_encoding_confidence_boundary_arousal_zero(self):
        conf = EmotionalField.encoding_confidence(VADVector(0.0, 0.0, 0.0))
        assert conf >= 0.45 and conf <= 0.55

    def test_encoding_confidence_boundary_arousal_max(self):
        conf = EmotionalField.encoding_confidence(VADVector(1.0, 1.0, 1.0))
        assert conf <= 1.0

    def test_emotion_shift_respects_max(self):
        mem = VADVector(-1.0, 0.0, -1.0)
        cur = VADVector(1.0, 0.0, 1.0)
        shifted = EmotionalField.emotion_shift(cur, mem, max_shift=0.1)
        # Should not flip sign with small max_shift
        assert shifted.valence < 0.0
